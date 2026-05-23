#!/bin/sh
# Download the Qwen2.5-3B-Instruct Q4_K_M GGUF model into /models if missing.
# Idempotent — safe to call on every worker startup.
set -eu

MODEL_DIR="${MODEL_DIR:-/models}"
MODEL_FILE="qwen2.5-3b-instruct-q4_k_m.gguf"
MODEL_PATH="${MODEL_DIR}/${MODEL_FILE}"
MODEL_URL="${MODEL_URL:-https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf?download=true}"
# Roughly 1.8 GB — refuse to consider the file "ready" unless it's > 1500 MB.
MIN_SIZE_BYTES="${MIN_SIZE_BYTES:-1500000000}"

mkdir -p "$MODEL_DIR"

if [ -f "$MODEL_PATH" ]; then
  size=$(stat -c%s "$MODEL_PATH" 2>/dev/null || stat -f%z "$MODEL_PATH")
  if [ "$size" -ge "$MIN_SIZE_BYTES" ]; then
    echo "[local-llm] model already present: $MODEL_PATH ($size bytes)"
    exit 0
  fi
  echo "[local-llm] model file present but too small ($size bytes) — re-downloading"
  rm -f "$MODEL_PATH"
fi

echo "[local-llm] downloading model from $MODEL_URL"
# Use curl with retries + resume capability
curl -L --fail --retry 5 --retry-delay 10 --continue-at - \
  -o "$MODEL_PATH.partial" \
  "$MODEL_URL"

mv "$MODEL_PATH.partial" "$MODEL_PATH"
size=$(stat -c%s "$MODEL_PATH" 2>/dev/null || stat -f%z "$MODEL_PATH")
echo "[local-llm] downloaded $size bytes to $MODEL_PATH"
