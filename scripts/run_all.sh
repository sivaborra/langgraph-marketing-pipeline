#!/bin/bash
# Phase 1 familiarisation demo — reproduces all 7 exercises.
# Usage: ./scripts/run_all.sh   (from the repo root, venv active)
set -e
cd "$(dirname "$0")/.."
PY=.venv/bin/python
mkdir -p runs checkpoints
echo "== Ex1 state/nodes/edges =="
$PY exercises/ex1_state_nodes_edges.py
echo "== Ex2 conditional =="
$PY exercises/ex2_conditional.py
echo "== Ex3 checkpoint crash/resume =="
rm -f runs/ex3_plan_done.txt checkpoints/ex3.db
$PY exercises/ex3_crash.py > runs/ex3_crash.log 2>&1 &
CRASH_PID=$!
for i in $(seq 1 30); do
  if [ -f runs/ex3_plan_done.txt ]; then break; fi
  sleep 1
done
cat runs/ex3_plan_done.txt
kill -9 $CRASH_PID || true
sleep 1
echo "killed pid $CRASH_PID with SIGKILL (simulated crash after plan)"
$PY exercises/ex3_resume.py
echo "== Ex4 interrupts =="
$PY exercises/ex4_interrupt.py
echo "== Ex5 streaming =="
$PY exercises/ex5_streaming.py
echo "== Ex6 subgraphs =="
$PY exercises/ex6_subgraph.py
echo "== Ex7 FastAPI smoke =="
./scripts/smoke_ex7.sh
echo "== ALL PHASE 1 EXERCISES DONE =="
ls -lh runs/ checkpoints/
