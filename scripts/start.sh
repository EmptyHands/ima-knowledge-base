#!/usr/bin/env bash
# 一键启动: 检查依赖 → Qdrant → Ollama → 后端 → 前端
set -e

cd "$(dirname "$0")/.."

echo "==> [1/5] 检查 .env"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "    已从 .env.example 生成 .env, 请填写 LLM_API_KEY 后重新运行"
  exit 1
fi

echo "==> [2/5] 检查 Python 依赖"
if [ ! -d venv ]; then
  python -m venv venv
fi
PY=venv/Scripts/python.exe
if [ ! -x "$PY" ] && [ -f venv/bin/python ]; then
  PY=venv/bin/python
fi
"$PY" -c "import fastapi, qdrant_client" 2>/dev/null || "$PY" -m pip install -r requirements.txt -q

echo "==> [3/5] 检查 Qdrant (端口 6333)"
if curl -s -o /dev/null http://localhost:6333/collections; then
  echo "    Qdrant 已在运行"
else
  if command -v docker >/dev/null 2>&1; then
    docker compose up -d qdrant
    sleep 3
  else
    echo "    ! 未安装 Docker: 请手动启动 Qdrant 后重试"
    echo "      参考: docker run -p 6333:6333 -p 6334:6334 qdrant/qdrant"
    exit 1
  fi
fi

echo "==> [4/5] 检查 Ollama embedding (端口 11434)"
if curl -s -o /dev/null http://localhost:11434/api/tags; then
  EMB_MODEL=$(grep EMBEDDING_MODEL .env | cut -d= -f2)
  if ! curl -s http://localhost:11434/api/tags | grep -q "\"$EMB_MODEL\""; then
    echo "    拉取 embedding 模型 $EMB_MODEL ..."
    ollama pull "$EMB_MODEL"
  fi
else
  echo "    ! Ollama 未运行: 请先启动 ollama serve, 然后拉取: ollama pull nomic-embed-text"
  exit 1
fi

echo "==> [5/5] 启动后端 + 前端"
"$PY" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!
trap 'kill $BACKEND_PID 2>/dev/null' EXIT

cd frontend
if [ ! -d node_modules ]; then
  npm install
fi
npm run dev

echo "启动完成: 前端 http://localhost:5173  后端 http://localhost:8000/docs"
