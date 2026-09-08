"""
Autonomous multi-step agent runtime for OLLM with background context compression.
Handles sliding window summarization and dynamic on-demand tool activation.
"""
import sys
import threading
from typing import List, Dict, Optional
from .config import (
    OLLMConfig,
    SYSTEM_INSTRUCTION,
    COLOR_RESET,
    COLOR_DIM,
    COLOR_TOOL,
    COLOR_ERR
)
from .tools import registry, parse_and_execute, load_custom_tools
from .engine import InferenceEngine

class StreamingANSIFormatter:
    """Stateful streaming filter that formats markdown (bolding, inline code) directly to terminal ANSI styles."""
    def __init__(self):
        self.buf = ""
        self.bold = False
        self.code = False

    def feed(self, text: str) -> str:
        self.buf += text
        out = []
        i = 0
        n = len(self.buf)
        while i < n:
            # Check for double asterisk (bold)
            if self.buf[i:i+2] == "**":
                self.bold = not self.bold
                out.append("\033[1m" if self.bold else "\033[22m")
                i += 2
                continue
            # Check for backtick (inline code)
            elif self.buf[i] == "`":
                self.code = not self.code
                out.append("\033[38;5;180m" if self.code else "\033[0m")
                i += 1
                continue
            # Retain trailing single asterisk if at end of buffer (may complete next token)
            elif i == n - 1 and self.buf[i] == "*":
                break
            else:
                out.append(self.buf[i])
                i += 1
        self.buf = self.buf[i:]
        return "".join(out)

    def flush(self) -> str:
        res = self.buf
        if self.bold:
            res += "\033[22m"
        if self.code:
            res += "\033[0m"
        self.buf = ""
        return res

class Agent:
    def __init__(self, config: OLLMConfig, engine: InferenceEngine):
        self.config = config
        self.engine = engine
        self.history: List[Dict[str, str]] = []
        self.tools_enabled = config.enable_tools
        self._compressing = False
        self._turns_since_compress = 0
        self._lock = threading.Lock()

        # Load any dynamic custom user tools
        load_custom_tools()
        self.reset()

    def reset(self):
        """Clears conversation context."""
        with self._lock:
            self.history = []
            if SYSTEM_INSTRUCTION:
                self.history.append({"role": "system", "content": SYSTEM_INSTRUCTION})
            self.tools_enabled = self.config.enable_tools
            self._turns_since_compress = 0

    def enable_tools(self) -> str:
        """Dynamically injects tool awareness into context only when requested."""
        with self._lock:
            self.tools_enabled = True
            # Clean any old tool note first to avoid duplicates
            self.history = [
                m for m in self.history
                if not (m.get("role") == "system" and "[Local tools enabled" in m.get("content", ""))
            ]
            tool_guide = (
                "[Local tools enabled. To run an action, output the XML tag:\n"
                "- <calc>math expression</calc>\n"
                "- <bash>command</bash>\n"
                "- <read path=\"file\" />\n"
                "- <write path=\"file\">content</write>\n"
                "- <find pattern=\"*\" />\n"
                "- <sysinfo />\n"
                "The tool result will be returned to you.]"
            )
            self.history.append({"role": "system", "content": tool_guide})
        return "[tools unlocked for conversation]"

    def disable_tools(self) -> str:
        """Deactivates tool mode and scrubs tool instructions from context."""
        with self._lock:
            self.tools_enabled = False
            self.history = [
                m for m in self.history
                if not (m.get("role") == "system" and "[Local tools enabled" in m.get("content", ""))
            ]
        return "[tools locked]"

    def _compress_context_sync(self):
        """
        Background task: summarizes older turns when context grows too long,
        preserving recent messages and any system prompt.
        Safe against concurrent append operations.
        """
        if self._compressing:
            return

        with self._lock:
            if len(self.history) <= 12:
                return
            self._compressing = True
            has_system = len(self.history) > 0 and self.history[0].get("role") == "system" and not self.history[0].get("content", "").startswith("[Summary")
            start_idx = 1 if has_system else 0
            compress_end_idx = len(self.history) - 6
            if compress_end_idx <= start_idx:
                self._compressing = False
                return
            slice_to_compress = self.history[start_idx:compress_end_idx]

            text_lines = []
            for m in slice_to_compress:
                content = m.get("content", "")
                if "[Local tools" in content:
                    continue
                text_lines.append(f"{m['role']}: {content}")
            text_snippet = "\n".join(text_lines)

        if not text_snippet.strip():
            self._compressing = False
            return

        # Generate a concise summary
        prompt = [
            {"role": "system", "content": "You are a fast summarizer. Condense the core facts, user preferences, and topics from this conversation into 1-2 ultra-short bullet points. Be extremely brief."},
            {"role": "user", "content": f"Conversation snippet:\n{text_snippet}\n\nKey points:"}
        ]

        summary_tokens = []
        try:
            for tok in self.engine.stream_chat(prompt, max_tokens=50):
                summary_tokens.append(tok)
            summary_text = "".join(summary_tokens).strip()

            if summary_text:
                with self._lock:
                    head = [self.history[0]] if has_system else []
                    self.history = [
                        *head,
                        {"role": "system", "content": f"[Summary of earlier conversation: {summary_text}]"},
                        *self.history[compress_end_idx:]
                    ]
                    self._turns_since_compress = 0
        except Exception:
            pass
        finally:
            self._compressing = False

    def trigger_background_compression(self):
        """Spawns a detached thread to compress context while user is thinking."""
        if len(self.history) > 12 and not self._compressing:
            t = threading.Thread(target=self._compress_context_sync, daemon=True)
            t.start()

    def execute_turn(self, user_prompt: str, stream_callback=None) -> str:
        """
        Executes a turn. Streams tokens with live formatting, supports Ctrl+C interruption,
        optionally dispatches tools if enabled, and triggers background context compression.
        """
        with self._lock:
            self.history.append({"role": "user", "content": user_prompt})

        step = 0
        final_text = ""

        while step < self.config.max_steps:
            step += 1
            accumulated_tokens: List[str] = []

            with self._lock:
                snapshot = list(self.history)

            formatter = StreamingANSIFormatter()
            interrupted = False

            # Stream generation with formatting and Ctrl+C interrupt handling
            try:
                for token in self.engine.stream_chat(snapshot):
                    accumulated_tokens.append(token)
                    if stream_callback:
                        stream_callback(token)
                    else:
                        rendered = formatter.feed(token)
                        if rendered:
                            sys.stdout.write(rendered)
                            sys.stdout.flush()
                if not stream_callback:
                    flushed = formatter.flush()
                    if flushed:
                        sys.stdout.write(flushed)
                        sys.stdout.flush()
            except KeyboardInterrupt:
                interrupted = True
                if not stream_callback:
                    sys.stdout.write(f"\033[0m\n{COLOR_DIM}[interrupted]{COLOR_RESET}\n")
                    sys.stdout.flush()

            full_response = "".join(accumulated_tokens)
            final_text = full_response

            with self._lock:
                if full_response.strip():
                    self.history.append({"role": "assistant", "content": full_response})

            if interrupted or not self.tools_enabled:
                break

            # Parse tool calls from model output
            tool_calls = parse_and_execute(full_response)
            if not tool_calls:
                break

            # Format and execute tool feedback
            sys.stdout.write("\n")
            tool_feedbacks = []
            for raw_tag, tool_name, result in tool_calls:
                if not self.config.quiet:
                    sys.stdout.write(f"{COLOR_TOOL}[tool:{tool_name}]{COLOR_RESET}\n")
                    for line in result.splitlines():
                        sys.stdout.write(f"{COLOR_DIM}  │ {line}{COLOR_RESET}\n")
                    sys.stdout.flush()

                tool_feedbacks.append(f"<tool_result name=\"{tool_name}\">\n{result}\n</tool_result>")

            payload = (
                "[Tool Results Received]\n"
                + "\n".join(tool_feedbacks)
                + "\n\nContinue with next step or provide final response."
            )
            with self._lock:
                self.history.append({"role": "user", "content": payload})

        sys.stdout.write("\n")
        sys.stdout.flush()

        # Update turn counter and trigger background compression if needed
        self._turns_since_compress += 1
        if self._turns_since_compress >= 5 or len(self.history) > 16:
            self.trigger_background_compression()

        return final_text
