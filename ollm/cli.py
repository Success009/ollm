"""
Command-line interface for OLLM with interactive Vim model selector and hot-swapping.
"""
import os
import sys
import gc
import argparse
import subprocess
from typing import Optional

def record_from_microphone() -> Optional[str]:
    """Records audio from system default microphone and queries speech-to-text."""
    audio_file = "/tmp/voice.wav"
    if os.path.exists(audio_file):
        try:
            os.remove(audio_file)
        except OSError:
            pass

    print(f"\n{COLOR_TOOL}🎤 Recording from mic... [Press Enter to finish and send]{COLOR_RESET}")
    proc = None
    try:
        # Start ffmpeg or arecord
        if subprocess.run(["which", "ffmpeg"], stdout=subprocess.DEVNULL).returncode == 0:
            proc = subprocess.Popen(
                ["ffmpeg", "-y", "-f", "alsa", "-i", "default", "-ac", "1", "-ar", "16000", audio_file],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        elif subprocess.run(["which", "arecord"], stdout=subprocess.DEVNULL).returncode == 0:
            proc = subprocess.Popen(
                ["arecord", "-D", "default", "-f", "cd", "-t", "wav", audio_file],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        else:
            print(f"{COLOR_ERR}Error: Neither ffmpeg nor arecord found for audio recording.{COLOR_RESET}")
            return None

        # Wait for user to press Enter to stop
        input()
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=0.5)
            except Exception:
                proc.kill()

    if not os.path.exists(audio_file) or os.path.getsize(audio_file) < 1000:
        print(f"{COLOR_DIM}[No audio captured]{COLOR_RESET}\n")
        return None

    # Transcribe: check whisper socket first
    text = ""
    if os.path.exists("/tmp/whisper_socket"):
        try:
            import socket
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(10.0)
            s.connect("/tmp/whisper_socket")
            s.sendall(b"go")
            text = s.recv(4096).decode("utf-8").strip()
            s.close()
        except Exception:
            pass

    # Fallback to faster-whisper if installed
    if not text:
        try:
            from faster_whisper import WhisperModel
            w_model = WhisperModel("base.en", device="cpu", compute_type="int8")
            segments, _ = w_model.transcribe(audio_file, beam_size=1)
            text = " ".join([seg.text for seg in segments]).strip()
        except Exception:
            pass

    if text:
        print(f"{COLOR_BOLD}🎤 Transcribed:{COLOR_RESET} {text}\n")
        return text
    else:
        print(f"{COLOR_DIM}[No speech detected]{COLOR_RESET}\n")
        return None

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
        print(f"{COLOR_DIM}Commands: /model (hot-swap), /voice (talk-back), /mic (voice input), /tools, /history, /exit{COLOR_RESET}")
        print(f"{COLOR_DIM}Voice Input: Type /mic or hold [Right Shift] anywhere to speak.{COLOR_RESET}\n")

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
            elif user_input in ("/mic", "/talk"):
                heard = record_from_microphone()
                if heard:
                    agent.execute_turn(heard)
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
