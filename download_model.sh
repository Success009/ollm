#!/usr/bin/env bash
set -e

MODEL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/models"
mkdir -p "$MODEL_DIR"

# Default: Llama 3.1 8B Instruct Abliterated (Q3_K_M, ~3.74 GB)
DEFAULT_URL="https://huggingface.co/mradermacher/Llama-3.1-8B-Instruct-abliterated-GGUF/resolve/main/Llama-3.1-8B-Instruct-abliterated.Q3_K_M.gguf"
TARGET_FILE="$MODEL_DIR/Llama-3.1-8B-Instruct-abliterated.Q3_K_M.gguf"

echo "=========================================================="
echo " Downloading Fully Abliterated Llama-3.1-8B (Q3_K_M GGUF) "
echo " Destination: $TARGET_FILE"
echo "=========================================================="

if [ -f "$TARGET_FILE" ]; then
    echo "Model file already exists. Checking completeness..."
fi

curl -L -C - --progress-bar "$DEFAULT_URL" -o "$TARGET_FILE"

echo ""
echo "Download complete! Model ready for 100% offline execution."
