#!/usr/bin/env bash
# Lokalno pokretanje u Docker-u; DeepSeek ključ iz ~/.claude-kp.env. Argumenti idu u vesti.py.
set -euo pipefail
cd "$(dirname "$0")"
DEEPSEEK_API_KEY=$(grep -oP '^\s*(export\s+)?DEEPSEEK_API_(KEY|TOKEN)\s*=\s*["'\'']?\K[^"'\''\s]+' ~/.claude-kp.env | head -1)
export DEEPSEEK_API_KEY
docker build -q -t boox-vesti . >/dev/null
docker run --rm -u "$(id -u):$(id -g)" -v "$PWD:/app" -e DEEPSEEK_API_KEY boox-vesti python vesti.py "$@"
