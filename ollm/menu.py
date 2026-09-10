"""
Interactive terminal model selector with Vim key navigation (j/k/l/Enter).
Zero dependencies, instant startup using standard termios/tty.
"""
import os
import sys
import tty
import termios
import subprocess
from typing import List, Dict, Optional, Any

from .config import (
    COLOR_PROMPT,
    COLOR_RESET,
    COLOR_DIM,
    COLOR_TOOL,
    COLOR_BOLD,
    COLOR_ERR
)

def get_system_specs() -> Dict[str, Any]:
    """Detects system RAM and GPU VRAM to determine model capability tiers."""
    total_ram_gb = 4.0
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    total_ram_gb = kb / (1024 * 1024)
                    break
    except Exception:
        pass

    gpu_name = None
    gpu_vram_gb = 0.0
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=1.0
        )
        if res.returncode == 0 and res.stdout.strip():
            parts = res.stdout.strip().split(",")
            gpu_name = parts[0].strip()
            if len(parts) > 1:
                gpu_vram_gb = float(parts[1].strip()) / 1024.0
    except Exception:
        pass

    return {
        "ram_gb": total_ram_gb,
        "gpu_name": gpu_name,
        "gpu_vram_gb": gpu_vram_gb,
        "has_gpu": gpu_name is not None
    }

KNOWN_MODELS = [
    # --- 1B - 2B Ultra-Light Class (Runs on <2GB RAM) ---
    {
        "id": "1b",
        "name": "Llama-3.2-1B-Instruct (Q4_K_M)",
        "file": "Llama-3.2-1B-Instruct-Q4_K_M.gguf",
        "size": "~0.8 GB",
        "req_ram": 1.5,
        "desc": "Meta Llama-3.2 1.2B Params │ 4-bit Medium │ Ultra-low RAM & battery efficient",
        "url": "https://huggingface.co/bartowski/Llama-3.2-1B-Instruct-GGUF/resolve/main/Llama-3.2-1B-Instruct-Q4_K_M.gguf"
    },
    {
        "id": "qwen1.5b",
        "name": "Qwen-2.5-1.5B-Instruct (Q4_K_M)",
        "file": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "size": "~1.0 GB",
        "req_ram": 2.0,
        "desc": "Alibaba Qwen-2.5 1.54B Params │ 4-bit Medium │ Math, code & dense logic specialist",
        "url": "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf"
    },

    # --- 3B - 4B Everyday Class (Runs on 4GB+ RAM) ---
    {
        "id": "3b",
        "name": "Llama-3.2-3B-Instruct-abliterated (Q4_K_M)",
        "file": "Llama-3.2-3B-Instruct-abliterated.Q4_K_M.gguf",
        "size": "~2.0 GB",
        "req_ram": 3.5,
        "desc": "Meta Llama-3.2 3.21B Params │ Abliterated / Uncensored │ Fast everyday companion",
        "url": "https://huggingface.co/mradermacher/Llama-3.2-3B-Instruct-abliterated-GGUF/resolve/main/Llama-3.2-3B-Instruct-abliterated.Q4_K_M.gguf"
    },
    {
        "id": "phi3.5",
        "name": "Phi-3.5-mini-instruct (Q4_K_M)",
        "file": "Phi-3.5-mini-instruct-Q4_K_M.gguf",
        "size": "~2.3 GB",
        "req_ram": 3.8,
        "desc": "Microsoft Phi-3.5 3.82B Params │ Dense multi-step reasoning & math",
        "url": "https://huggingface.co/bartowski/Phi-3.5-mini-instruct-GGUF/resolve/main/Phi-3.5-mini-instruct-Q4_K_M.gguf"
    },

    # --- 7B - 8B Mid-Tier Workhorses (Runs on 8GB+ RAM) ---
    {
        "id": "8b",
        "name": "Llama-3.1-8B-Instruct-abliterated (Q3_K_M)",
        "file": "Llama-3.1-8B-Instruct-abliterated.Q3_K_M.gguf",
        "size": "~3.8 GB",
        "req_ram": 5.5,
        "desc": "Meta Llama-3.1 8.03B Params │ Abliterated / Uncensored │ Broad world knowledge",
        "url": "https://huggingface.co/mradermacher/Llama-3.1-8B-Instruct-abliterated-GGUF/resolve/main/Llama-3.1-8B-Instruct-abliterated.Q3_K_M.gguf"
    },
    {
        "id": "mistral7b",
        "name": "Mistral-7B-Instruct-v0.3-abliterated (Q4_K_M)",
        "file": "Mistral-7B-Instruct-v0.3-abliterated.Q4_K_M.gguf",
        "size": "~4.3 GB",
        "req_ram": 6.5,
        "desc": "Mistral AI 7.25B Params │ Abliterated / Uncensored │ Flagship European reasoning",
        "url": "https://huggingface.co/mradermacher/Mistral-7B-Instruct-v0.3-abliterated-GGUF/resolve/main/Mistral-7B-Instruct-v0.3-abliterated.Q4_K_M.gguf"
    },
    {
        "id": "hermes8b",
        "name": "Hermes-3-Llama-3.1-8B (Q4_K_M)",
        "file": "Hermes-3-Llama-3.1-8B.Q4_K_M.gguf",
        "size": "~4.9 GB",
        "req_ram": 6.5,
        "desc": "NousResearch Hermes-3 8B │ Advanced agentic roleplay & unaligned reasoning",
        "url": "https://huggingface.co/NousResearch/Hermes-3-Llama-3.1-8B-GGUF/resolve/main/Hermes-3-Llama-3.1-8B.Q4_K_M.gguf"
    },
    {
        "id": "r1",
        "name": "DeepSeek-R1-Distill-Qwen-7B (Q4_K_M)",
        "file": "DeepSeek-R1-Distill-Qwen-7B.Q4_K_M.gguf",
        "size": "~4.7 GB",
        "req_ram": 7.0,
        "desc": "DeepSeek R1 Reasoning Model │ Chain-of-thought tokens │ Deep analysis & math",
        "url": "https://huggingface.co/mradermacher/DeepSeek-R1-Distill-Qwen-7B-GGUF/resolve/main/DeepSeek-R1-Distill-Qwen-7B.Q4_K_M.gguf"
    },

    # --- 12B - 14B Heavy Reasoning (Runs on 12GB - 16GB RAM) ---
    {
        "id": "nemo12b",
        "name": "Mistral-Nemo-12B-abliterated (Q4_K_M)",
        "file": "Mistral-Nemo-Instruct-2407-abliterated.Q4_K_M.gguf",
        "size": "~7.5 GB",
        "req_ram": 9.5,
        "desc": "Mistral AI + NVIDIA 12.2B Params │ Abliterated │ 128k context & precision coding",
        "url": "https://huggingface.co/mradermacher/Mistral-Nemo-Instruct-2407-abliterated-GGUF/resolve/main/Mistral-Nemo-Instruct-2407-abliterated.Q4_K_M.gguf"
    },
    {
        "id": "14b",
        "name": "Qwen-2.5-14B-Instruct-abliterated (Q3_K_M)",
        "file": "Qwen2.5-14B-Instruct-abliterated.Q3_K_M.gguf",
        "size": "~7.5 GB",
        "req_ram": 10.0,
        "desc": "Alibaba Qwen-2.5 14.77B Params │ Abliterated │ Elite code generation & logic",
        "url": "https://huggingface.co/mradermacher/Qwen2.5-14B-Instruct-abliterated-GGUF/resolve/main/Qwen2.5-14B-Instruct-abliterated.Q3_K_M.gguf"
    },
    {
        "id": "14b-q4",
        "name": "Qwen-2.5-14B-Instruct-abliterated (Q4_K_M)",
        "file": "Qwen2.5-14B-Instruct-abliterated.Q4_K_M.gguf",
        "size": "~9.0 GB",
        "req_ram": 11.5,
        "desc": "Alibaba Qwen-2.5 14.77B Params │ 4-bit High Fidelity │ Maximum 14B accuracy",
        "url": "https://huggingface.co/mradermacher/Qwen2.5-14B-Instruct-abliterated-GGUF/resolve/main/Qwen2.5-14B-Instruct-abliterated.Q4_K_M.gguf"
    },

    # --- 24B - 32B Flagship Giants (Runs on 16GB+ RAM / High VRAM) ---
    {
        "id": "mistral24b",
        "name": "Mistral-Small-24B-Instruct-abliterated (Q3_K_M)",
        "file": "Mistral-Small-24B-Instruct-2501-abliterated.Q3_K_M.gguf",
        "size": "~11.2 GB",
        "req_ram": 13.5,
        "desc": "Mistral AI 24B Flagship │ Abliterated │ Massive reasoning power for 16GB systems",
        "url": "https://huggingface.co/mradermacher/Mistral-Small-24B-Instruct-2501-abliterated-GGUF/resolve/main/Mistral-Small-24B-Instruct-2501-abliterated.Q3_K_M.gguf"
    },
    {
        "id": "gemma27b",
        "name": "Gemma-2-27B-IT-abliterated (Q3_K_M)",
        "file": "gemma-2-27b-it-abliterated.Q3_K_M.gguf",
        "size": "~12.5 GB",
        "req_ram": 14.5,
        "desc": "Google DeepMind 27B Params │ Abliterated │ Outstanding benchmark performance",
        "url": "https://huggingface.co/mradermacher/gemma-2-27b-it-abliterated-GGUF/resolve/main/gemma-2-27b-it-abliterated.Q3_K_M.gguf"
    },
    {
        "id": "32b-q2",
        "name": "Qwen-2.5-32B-Instruct-abliterated (Q2_K)",
        "file": "Qwen2.5-32B-Instruct-abliterated.Q2_K.gguf",
        "size": "~11.5 GB",
        "req_ram": 13.5,
        "desc": "Qwen-2.5 32.5B Giant │ Compressed 2-bit │ Runs huge 32B model on 16GB RAM machines",
        "url": "https://huggingface.co/mradermacher/Qwen2.5-32B-Instruct-abliterated-GGUF/resolve/main/Qwen2.5-32B-Instruct-abliterated.Q2_K.gguf"
    },
    {
        "id": "32b-q3",
        "name": "Qwen-2.5-32B-Instruct-abliterated (Q3_K_M)",
        "file": "Qwen2.5-32B-Instruct-abliterated.Q3_K_M.gguf",
        "size": "~14.2 GB",
        "req_ram": 15.5,
        "desc": "Qwen-2.5 32.5B Giant │ 3-bit Medium │ Frontier-level reasoning (Requires 16GB RAM)",
        "url": "https://huggingface.co/mradermacher/Qwen2.5-32B-Instruct-abliterated-GGUF/resolve/main/Qwen2.5-32B-Instruct-abliterated.Q3_K_M.gguf"
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

def download_model(model_info: Dict[str, Any]) -> str:
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
    Renders an interactive spec-aware menu navigated via j/k/l/Enter with a smooth scrolling viewport.
    Locks models exceeding available RAM with clear warnings and recommendations.
    """
    import shutil
    specs = get_system_specs()
    ram_gb = specs["ram_gb"]
    gpu_desc = f"{specs['gpu_name']} ({specs['gpu_vram_gb']:.1f}GB VRAM)" if specs["has_gpu"] else "CPU Mode"

    models_dir = get_models_dir()

    # Identify which models exist on disk and check system compatibility
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

        m["path"] = found_path if found_path else os.path.join(models_dir, m["file"])
        m["installed"] = found_path is not None
        m["locked"] = ram_gb < m.get("req_ram", 4.0)

    # Determine recommended model (highest tier model that fits comfortably within 75% of RAM)
    recommended_idx = 0
    for idx, m in enumerate(KNOWN_MODELS):
        if m.get("req_ram", 4.0) <= ram_gb * 0.75:
            recommended_idx = idx

    selected_idx = 0
    if current_file:
        for i, m in enumerate(KNOWN_MODELS):
            if os.path.basename(current_file) == m["file"]:
                selected_idx = i
                break
    else:
        # Default to current installed or recommended
        first_installed = next((i for i, m in enumerate(KNOWN_MODELS) if m["installed"]), None)
        selected_idx = first_installed if first_installed is not None else recommended_idx

    # Hide cursor
    sys.stdout.write("\033[?25l")
    sys.stdout.flush()

    total = len(KNOWN_MODELS)

    def render():
        # Terminal height-aware viewport
        term_lines = shutil.get_terminal_size((80, 24)).lines
        visible_count = max(4, min(6, (term_lines - 7) // 2))

        # Viewport windowing around selected_idx
        start_idx = max(0, min(selected_idx - visible_count // 2, total - visible_count))
        end_idx = min(total, start_idx + visible_count)

        output = [
            f"\n{COLOR_BOLD}OLLM Model Hub{COLOR_RESET} {COLOR_DIM}│ Hardware: {ram_gb:.1f}GB RAM, {gpu_desc} │ [{selected_idx + 1}/{total}]{COLOR_RESET}",
            f"{COLOR_DIM}(j/k to navigate, Enter to load, q to exit){COLOR_RESET}"
        ]

        if start_idx > 0:
            output.append(f"   {COLOR_DIM}▲ ({start_idx} smaller models above){COLOR_RESET}")
        else:
            output.append("")

        for idx in range(start_idx, end_idx):
            m = KNOWN_MODELS[idx]
            if m["installed"]:
                status = f"{COLOR_DIM}[Downloaded]{COLOR_RESET}"
            elif m["locked"]:
                status = f"{COLOR_ERR}[Locked 🔒 - Needs {m['req_ram']:.0f}GB RAM]{COLOR_RESET}"
            elif idx == recommended_idx:
                status = f"{COLOR_BOLD}\033[38;5;82m[Recommended ⭐]{COLOR_RESET}"
            else:
                status = f"{COLOR_TOOL}[Compatible]{COLOR_RESET}"

            marker = f"{COLOR_PROMPT}❯{COLOR_RESET}" if idx == selected_idx else " "
            name_str = f"{COLOR_BOLD}{m['name']}{COLOR_RESET}" if idx == selected_idx else m['name']
            output.append(f" {marker} [{idx + 1}] {name_str} - {m['size']} {status}")
            output.append(f"       {COLOR_DIM}↳ {m['desc']}{COLOR_RESET}")

        if end_idx < total:
            output.append(f"   {COLOR_DIM}▼ ({total - end_idx} larger models below){COLOR_RESET}")

        return "\n".join(output)

    try:
        prev_lines_count = 0
        while True:
            rendered = render()
            if prev_lines_count > 0:
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
                chosen = KNOWN_MODELS[selected_idx]
                if chosen["locked"] and not chosen["installed"]:
                    sys.stdout.write("\033[?25h")
                    sys.stdout.flush()
                    print(f"\n{COLOR_ERR}⚠️ High Memory Warning:{COLOR_RESET} {chosen['name']} requires ~{chosen['req_ram']:.0f}GB RAM.")
                    print(f"{COLOR_DIM}Your machine has {ram_gb:.1f}GB RAM. Running it may cause heavy freezing/swapping.{COLOR_RESET}")
                    resp = input(f"{COLOR_TOOL}Download and run anyway? (y/N): {COLOR_RESET}").strip().lower()
                    sys.stdout.write("\033[?25l")
                    sys.stdout.flush()
                    if resp == 'y':
                        break
                    else:
                        prev_lines_count = 0
                        continue
                break
            elif key in ("q", "esc", "ctrl_c"):
                sys.stdout.write("\033[?25h\n")
                sys.stdout.flush()
                return None

    finally:
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()

    chosen = KNOWN_MODELS[selected_idx]
    if not chosen["installed"]:
        download_model(chosen)

    return chosen["path"]
