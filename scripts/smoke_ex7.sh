#!/bin/bash
# Ex7 smoke test: start uvicorn, curl /healthz, /run, /runs, kill, save transcript.
# Usage: ./scripts/smoke_ex7.sh   (from the repo root, venv active)
set -e
cd "$(dirname "$0")/.."
mkdir -p runs
.venv/bin/uvicorn exercises.ex7_api:app --port 8001 > runs/ex7_uvicorn.log 2>&1 &
UV_PID=$!
trap "kill $UV_PID 2>/dev/null || true" EXIT
for i in $(seq 1 30); do
  if curl -s http://127.0.0.1:8001/healthz >/dev/null 2>&1; then break; fi
  sleep 1
done
{
  echo "GET /healthz:"
  curl -s -w "\nHTTP %{http_code}\n" http://127.0.0.1:8001/healthz
  echo "POST /run:"
  curl -s -w "\nHTTP %{http_code}\n" -X POST http://127.0.0.1:8001/run -H 'Content-Type: application/json' -d '{"topic":"LangGraph orchestration for Example Consulting"}'
  echo "GET /runs:"
  curl -s -w "\nHTTP %{http_code}\n" http://127.0.0.1:8001/runs
} | tee runs/ex7_smoke.txt
grep -q '"status": "ok"' runs/ex7_smoke.txt || grep -q '"status":"ok"' runs/ex7_smoke.txt
grep -q "HTTP 200" runs/ex7_smoke.txt
echo "Ex7 smoke PASSED: /healthz 200"
