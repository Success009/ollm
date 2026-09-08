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
        quiet=args.quiet
    )
    if not config.quiet:
        print(f"{COLOR_DIM}Loading {os.path.basename(model_path)} into memory...{COLOR_RESET}")

    try:
        engine = InferenceEngine(config)
    except Exception as e:
        print(f"{COLOR_ERR}Engine initialization failed: {e}{COLOR_RESET}", file=sys.stderr)
        sys.exit(1)

    agent = Agent(config, engine)

    # Case 1: Single-shot execution
    if args.prompt or piped_data:
        user_query = " ".join(args.prompt).strip()
        if piped_data and user_query:
            combined = f"{user_query}\n\n[Input Data]:\n{piped_data}"
        elif piped_data:
            combined = piped_data
        else:
            combined = user_query

        agent.execute_turn(combined)
        return

    # Case 2: Interactive REPL
    if not config.quiet:
        model_name = os.path.basename(model_path)
        print(f"{COLOR_DIM}ollm ready :: {model_name} (threads: {config.threads}){COLOR_RESET}")
        print(f"{COLOR_DIM}Commands: /model (hot-swap), /reset, /tools, /exit{COLOR_RESET}\n")

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
