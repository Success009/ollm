"""
Command-line interface for OLLM with interactive Vim model selector and hot-swapping.
"""
import os
import sys
import gc
import argparse
from typing import Optional

from .config import (
    OLLMConfig,
    find_available_model,
    COLOR_PROMPT,
    COLOR_RESET,
    COLOR_DIM,
    COLOR_ERR,
    COLOR_TOOL,
    COLOR_BOLD
)
from .menu import select_model_interactive, KNOWN_MODELS, get_models_dir
from .tools import registry, load_custom_tools
from .engine import InferenceEngine
from .agent import Agent

def resolve_model_arg(arg: Optional[str]) -> Optional[str]:
    """Resolves short aliases (3b, 8b) or file paths to absolute model path."""
    if not arg:
        return None
    models_dir = get_models_dir()
    for m in KNOWN_MODELS:
        if arg.lower() in (m["id"], m["file"].lower(), m["name"].lower()):
            return os.path.join(models_dir, m["file"])
    if os.path.exists(arg):
        return os.path.abspath(arg)
    return None

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ollm",
        description="OLLM: High-efficiency offline LLM CLI with recursive tool execution."
    )
    parser.add_argument("prompt", nargs="*", default=[], help="Prompt to execute (optional)")
    parser.add_argument("-m", "--model", type=str, default=None, help="Model alias ('3b', '8b') or path to GGUF")
    parser.add_argument("-t", "--threads", type=int, default=4, help="CPU threads (default: 4)")
    parser.add_argument("-c", "--ctx", type=int, default=3072, help="Context size in tokens (default: 3072)")
    parser.add_argument("-s", "--max-steps", type=int, default=8, help="Max recursive tool hops (default: 8)")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress status indicators")
    parser.add_argument("--tools", action="store_true", help="Enable XML tool execution")
    parser.add_argument("--voice", action="store_true", help="Enable parallel real-time voice speech output")
    parser.add_argument("--list-tools", action="store_true", help="List registered tools and exit")
    return parser
def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.list_tools:
        load_custom_tools()
        for t in registry.list_tools():
            print(f"- {t.name}: {t.description}")
        return

    # Check for piped input
    piped_data = ""
    if not sys.stdin.isatty():
        piped_data = sys.stdin.read().strip()

    model_path = resolve_model_arg(args.model)

    # If running interactive REPL and no model specified, show the clean TUI picker
    if not model_path and not args.prompt and not piped_data:
        model_path = select_model_interactive()
        if not model_path:
            sys.exit(0)

    # Fallback search if still unresolved
    if not model_path:
        model_path = find_available_model(args.model)

    if not model_path or not os.path.exists(model_path):
        print(f"{COLOR_ERR}Error: No model found.{COLOR_RESET}", file=sys.stderr)
        model_path = select_model_interactive()
        if not model_path:
            sys.exit(1)

    config = OLLMConfig(
        model_path=model_path,
        threads=args.threads,
        ctx_size=args.ctx,
        max_steps=args.max_steps,
        enable_tools=args.tools,
        enable_voice=args.voice,
        quiet=args.quiet
    )

    engine = InferenceEngine(config)
    agent = Agent(config, engine)

    # Case 1: Piped UNIX stream or CLI positional arguments
    if piped_data or args.prompt:
        user_query = " ".join(args.prompt)
        if piped_data:
            full_prompt = f"{piped_data}\n\n{user_query}" if user_query else piped_data
        else:
            full_prompt = user_query
        agent.execute_turn(full_prompt)
        return

    # Case 2: Interactive REPL
    if not config.quiet:
        model_name = os.path.basename(model_path)
        voice_tag = f" {COLOR_TOOL}[Voice: ON]{COLOR_RESET}" if config.enable_voice else ""
        print(f"{COLOR_DIM}ollm ready :: {model_name} (threads: {config.threads}){voice_tag}{COLOR_RESET}")
        print(f"{COLOR_DIM}Commands: /model (hot-swap), /voice (toggle talk-back), /tools, /reset, /exit{COLOR_RESET}")
        print(f"{COLOR_DIM}Voice Input: Hold [Right Shift] to speak, release to send.{COLOR_RESET}\n")

    while True:
        try:
            prompt_str = f"{COLOR_PROMPT}ollm ❯{COLOR_RESET} "
            user_input = input(prompt_str).strip()
            if not user_input:
                continue

            if user_input in ("/exit", "/quit", "/q"):
                break
            elif user_input in ("/reset", "/clear", "/c"):
                agent.reset()
                print(f"{COLOR_DIM}[context cleared]{COLOR_RESET}")
                continue
            elif user_input in ("/model", "/swap", "/switch", "/m"):
                # Interactive hot-swap
                new_model = select_model_interactive(current_file=config.model_path)
                if new_model and new_model != config.model_path:
                    print(f"\n{COLOR_DIM}Unloading current model and loading {os.path.basename(new_model)}...{COLOR_RESET}")
                    # Free memory
                    del agent.engine.llm
                    del agent.engine
                    gc.collect()
                    config.model_path = new_model
                    agent.engine = InferenceEngine(config)
                    print(f"{COLOR_BOLD}[✓] Swapped to {os.path.basename(new_model)}{COLOR_RESET}\n")
                continue
            elif user_input in ("/tools", "/tool"):
                print(f"\n{COLOR_TOOL}Available tools:{COLOR_RESET}")
                for t in registry.list_tools():
                    print(f"  • {t.name}: {t.description}")
                status = agent.enable_tools()
                print(f"{COLOR_DIM}{status} (use '/notools' to disable){COLOR_RESET}\n")
                continue
            elif user_input in ("/notools", "/tools off"):
                status = agent.disable_tools()
                print(f"{COLOR_DIM}{status}{COLOR_RESET}")
                continue
            elif user_input in ("/voice", "/v"):
                is_active = agent.voice.toggle()
                status = "ENABLED" if is_active else "DISABLED"
                color = COLOR_TOOL if is_active else COLOR_DIM
                print(f"{color}[Voice talk-back {status}]{COLOR_RESET} (Speaks responses sentence-by-sentence in background)")
                continue
            elif user_input in ("/history", "/h"):
                with agent._lock:
                    count = len(agent.history)
                    has_summary = any("Summary of earlier" in m.get("content", "") for m in agent.history)
                summary_tag = " [compressed]" if has_summary else ""
                print(f"{COLOR_DIM}History turns: {count}{summary_tag}{COLOR_RESET}")
                continue

            agent.execute_turn(user_input)

        except (KeyboardInterrupt, EOFError):
            print("\n")
            break

if __name__ == "__main__":
    main()
