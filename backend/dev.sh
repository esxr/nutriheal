#!/bin/bash

# kill any running ports
kill -9 $(lsof -i:11434 -t) 2>/dev/null # ollama
kill -9 $(lsof -i:8080 -t) 2>/dev/null # webui
kill -9 $(lsof -i:8000 -t) 2>/dev/null # pebblo

source /Users/user/opt/anaconda3/etc/profile.d/conda.sh
conda activate pebblo_demo

# start ollama
ollama serve &

# attach pebblo
pebblo &

PORT="${PORT:-8080}"
uvicorn main:app --port $PORT --host 0.0.0.0 --forwarded-allow-ips '*' --reload

# kill any running ports
kill -9 $(lsof -i:11434 -t) 2>/dev/null # ollama
kill -9 $(lsof -i:8080 -t) 2>/dev/null # webui
kill -9 $(lsof -i:8000 -t) 2>/dev/null # pebblo