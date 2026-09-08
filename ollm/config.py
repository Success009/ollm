"""
Configuration defaults, model locator, and terminal theme settings for OLLM.
"""
import os
import glob
from dataclasses import dataclass
from typing import Optional, List

DEFAULT_MODEL_URL = "https://huggingface.co/mradermacher/Llama-3.1-8B-Instruct-abliterated-GGUF/resolve/main/Llama-3.1-8B-Instruct-abliterated.Q3_K_M.gguf"
DEFAULT_MODEL_NAME = "Llama-3.1-8B-Instruct-abliterated.Q3_K_M.gguf"

# Muted ANSI colors for a clean terminal interface
COLOR_PROMPT = "\033[38;5;39m"     # Subtle cyan/blue
COLOR_DIM = "\033[38;5;242m"       # Muted gray
COLOR_TOOL = "\033[38;5;214m"      # Amber/orange for tool headers
COLOR_ERR = "\033[38;5;196m"       # Soft red
COLOR_RESET = "\033[0m"
COLOR_BOLD = "\033[1m"

SYSTEM_INSTRUCTION = (
    "You are OLLM, a fast offline language model created by success and running locally on this machine.\n"
    "Respond in a natural, conversational manner. Keep replies concise (1 to 3 sentences) unless the user explicitly asks for detail or an explanation.\n"
    "Do not yap, give unsolicited essays, or emit bulleted lists unless requested. If asked who you are or what OLLM is, you are OLLM running offline here."
)

@dataclass
class OLLMConfig:
    model_path: str
    threads: int = 4
    ctx_size: int = 2048
    max_steps: int = 8
    temperature: float = 0.6
    top_p: float = 0.9
    enable_tools: bool = False
    quiet: bool = False
def find_available_model(explicit_path: Optional[str] = None) -> Optional[str]:
    """Locate a GGUF model from CLI argument or standard system locations."""
    if explicit_path and os.path.exists(explicit_path):
        return os.path.abspath(explicit_path)

    search_dirs = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models"),
        os.path.expanduser("~/.local/share/ollm/models"),
        os.path.expanduser("~/.cache/ollm/models"),
        os.path.join(os.getcwd(), "models"),
        os.getcwd(),
    ]

    for directory in search_dirs:
        if not os.path.isdir(directory):
            continue
        ggufs = glob.glob(os.path.join(directory, "*.gguf"))
        if ggufs:
            # Sort by size descending or preference
            return sorted(ggufs, key=os.path.getsize, reverse=True)[0]

    return None
