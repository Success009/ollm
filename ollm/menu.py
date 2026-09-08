"""
Interactive terminal model selector with Vim key navigation (j/k/l/Enter).
Zero dependencies, instant startup using standard termios/tty.
"""
import os
import sys
import tty
import termios
import subprocess
from typing import List, Dict, Optional

from .config import (
    COLOR_PROMPT,
    COLOR_RESET,
    COLOR_DIM,
    COLOR_TOOL,
    COLOR_BOLD,
    COLOR_ERR
)

KNOWN_MODELS = [
    {
        "id": "3b",
        "name": "Llama-3.2-3B-Instruct-abliterated (Q4_K_M)",
        "file": "Llama-3.2-3B-Instruct-abliterated.Q4_K_M.gguf",
        "size": "~2.0 GB",
        "desc": "Fast (~6-8 tok/s, instant start, ~2.2GB RAM)",
        "url": "https://huggingface.co/mradermacher/Llama-3.2-3B-Instruct-abliterated-GGUF/resolve/main/Llama-3.2-3B-Instruct-abliterated.Q4_K_M.gguf"
    },
    {
        "id": "8b",
        "name": "Llama-3.1-8B-Instruct-abliterated (Q3_K_M)",
        "file": "Llama-3.1-8B-Instruct-abliterated.Q3_K_M.gguf",
        "size": "~3.8 GB",
        "desc": "Smarter (~1.5 tok/s, deeper reasoning, ~4.2GB RAM)",
        "url": "https://huggingface.co/mradermacher/Llama-3.1-8B-Instruct-abliterated-GGUF/resolve/main/Llama-3.1-8B-Instruct-abliterated.Q3_K_M.gguf"
    }
]

def get_key() -> str:
    """Read a single keypress or escape sequence from stdin."""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":  # Escape sequence
            ch2 = sys.stdin.read(1)
            if ch2 == "[":
                ch3 = sys.stdin.read(1)
                if ch3 == "A":
                    return "up"
                elif ch3 == "B":
                    return "down"
                elif ch3 == "C":
                    return "right"
                elif ch3 == "D":
                    return "left"
            return "esc"
        elif ch in ("\r", "\n"):
            return "enter"
        elif ch == "\x03":  # Ctrl+C
            return "ctrl_c"
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

def get_models_dir() -> str:
    # First priority: project local models dir if writable
    repo_models = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models")
    if os.path.isdir(repo_models) and os.access(repo_models, os.W_OK):
        return repo_models
    # Standard user share directory
    user_models = os.path.expanduser("~/.local/share/ollm/models")
    os.makedirs(user_models, exist_ok=True)
    return user_models

def download_model(model_info: Dict[str, str]) -> str:
    target_path = os.path.join(get_models_dir(), model_info["file"])
    print(f"\n{COLOR_TOOL}[*] Downloading {model_info['name']}...{COLOR_RESET}")
    print(f"{COLOR_DIM}URL: {model_info['url']}{COLOR_RESET}")
    cmd = ["curl", "-L", "-C", "-", "--progress-bar", model_info["url"], "-o", target_path]
    try:
        subprocess.run(cmd, check=True)
        print(f"{COLOR_BOLD}[✓] Download complete.{COLOR_RESET}\n")
        return target_path
    except Exception as e:
        print(f"{COLOR_ERR}Download failed: {e}{COLOR_RESET}", file=sys.stderr)
        sys.exit(1)

def select_model_interactive(current_file: Optional[str] = None) -> Optional[str]:
    """
    Renders an interactive menu navigated via j/k/l/Enter.
    Returns the absolute path of the selected model.
    """
    models_dir = get_models_dir()

    # Identify which models exist on disk
    for m in KNOWN_MODELS:
        candidate_paths = [
            os.path.join(models_dir, m["file"]),
            os.path.expanduser(f"~/.local/share/ollm/models/{m['file']}"),
            os.path.expanduser(f"~/.cache/ollm/models/{m['file']}"),
            os.path.join(os.getcwd(), "models", m["file"])
        ]
        found_path = None
        for cp in candidate_paths:
            if os.path.exists(cp):
                found_path = cp
                break
        if found_path:
            m["path"] = found_path
            m["installed"] = True
        else:
            m["path"] = os.path.join(models_dir, m["file"])
            m["installed"] = False

    selected_idx = 0
    # Default selection to current or first installed
    if current_file:
        for i, m in enumerate(KNOWN_MODELS):
            if os.path.basename(current_file) == m["file"]:
                selected_idx = i
                break

    # Hide cursor
    sys.stdout.write("\033[?25l")
    sys.stdout.flush()

    total = len(KNOWN_MODELS)

    def render():
        # Clear previous lines
        output = [
            f"\n{COLOR_BOLD}Select Model{COLOR_RESET} {COLOR_DIM}(j/k to move, Enter/l to select, q to exit):{COLOR_RESET}\n"
        ]
        for idx, m in enumerate(KNOWN_MODELS):
            status = f"{COLOR_DIM}[Downloaded]{COLOR_RESET}" if m["installed"] else f"{COLOR_TOOL}[Download Required]{COLOR_RESET}"
            marker = f"{COLOR_PROMPT}❯{COLOR_RESET}" if idx == selected_idx else " "
            name_str = f"{COLOR_BOLD}{m['name']}{COLOR_RESET}" if idx == selected_idx else m['name']
            output.append(f" {marker} [{idx + 1}] {name_str} - {m['size']} {status}")
            output.append(f"       {COLOR_DIM}↳ {m['desc']}{COLOR_RESET}")
        return "\n".join(output)

    try:
        prev_lines_count = 0
        while True:
            rendered = render()
            if prev_lines_count > 0:
                # Move cursor back up and clear
                sys.stdout.write(f"\033[{prev_lines_count}A\033[J")
            sys.stdout.write(rendered + "\n")
            sys.stdout.flush()
            prev_lines_count = rendered.count("\n") + 1

            key = get_key()
            if key in ("k", "up"):
                selected_idx = (selected_idx - 1) % total
            elif key in ("j", "down"):
                selected_idx = (selected_idx + 1) % total
            elif key in ("enter", "l"):
                break
            elif key in ("q", "esc", "ctrl_c"):
                sys.stdout.write("\033[?25h\n")
                sys.stdout.flush()
                return None

    finally:
        # Restore cursor
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()

    chosen = KNOWN_MODELS[selected_idx]
    if not chosen["installed"]:
        download_model(chosen)

    return chosen["path"]
