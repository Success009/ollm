"""
Llama engine wrapper for OLLM with persistent disk KV-caching.
Eliminates first-token cold start delay by persisting prompt evaluations to SSD.
"""
import os
import sys
import threading
from typing import Generator, List, Dict, Any, Sequence
from .config import OLLMConfig

try:
    from llama_cpp import Llama, LlamaDiskCache
except ImportError:
    Llama = None
    LlamaDiskCache = None

class SilentDiskCache(LlamaDiskCache):
    """Subclass of LlamaDiskCache that suppresses hardcoded debug prints."""
    def __setitem__(self, key: Sequence[int], value: Any):
        key = tuple(key)
        if key in self.cache:
            try:
                del self.cache[key]
            except KeyError:
                pass
        self.cache[key] = value
        while self.cache_size > self.capacity_bytes and len(self.cache) > 0:
            try:
                key_to_remove = next(iter(self.cache))
                del self.cache[key_to_remove]
            except (KeyError, StopIteration):
                break

class InferenceEngine:
    def __init__(self, config: OLLMConfig):
        if Llama is None:
            raise RuntimeError("llama-cpp-python is required. Install with: pip install llama-cpp-python")

        self.config = config
        self.lock = threading.Lock()

                # Check for GPU capability and configure layer offload
        from .menu import get_system_specs
        specs = get_system_specs()
        n_gpu_layers = -1 if specs.get("has_gpu") else 0

        # Initialize llama with CPU/GPU optimizations
        self.llm = Llama(
            model_path=config.model_path,
            n_ctx=config.ctx_size,
            n_threads=config.threads,
            n_gpu_layers=n_gpu_layers,
            n_batch=512,
            use_mmap=True,
            use_mlock=False,
            verbose=False
        )

        # Persistent disk cache partitioned per model architecture
        if LlamaDiskCache is not None:
            model_key = os.path.splitext(os.path.basename(config.model_path))[0]
            cache_dir = os.path.expanduser(f"~/.cache/ollm/kv_cache/{model_key}")
            os.makedirs(cache_dir, exist_ok=True)
            cache = SilentDiskCache(cache_dir=cache_dir, capacity_bytes=512 * 1024 * 1024)
            self.llm.set_cache(cache)

    def stream_chat(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 1024
    ) -> Generator[str, None, None]:
        """Yields output tokens in real time protected by engine lock."""
        with self.lock:
            response_stream = self.llm.create_chat_completion(
                messages=messages,
                temperature=self.config.temperature,
                top_p=self.config.top_p,
                stream=True,
                max_tokens=max_tokens
            )
            for chunk in response_stream:
                choices = chunk.get("choices", [])
                if not choices:
                    continue
                delta = choices[0].get("delta", {})
                content = delta.get("content", "")
                if content:
                    yield content
