#!/usr/bin/env bash
# End-to-end VisionForge demo, from nothing: creates a venv, installs
# dependencies, generates the synthetic test clip if it doesn't exist yet,
# runs the full offline reconstruction pipeline (with --persist), starts the
# read-only/persist API, and starts the frontend dev server pointed at it.
#
# Usage: scripts/run_demo.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

VENV_DIR="$REPO_ROOT/.venv"
CLIP="$REPO_ROOT/data/input/synthetic_box_room.mp4"
RUN_DIR="$REPO_ROOT/outputs/demo"

echo "== VisionForge end-to-end demo =="
echo "Repo root: $REPO_ROOT"

if [ ! -d "$VENV_DIR" ]; then
    echo "[1/6] Creating venv at $VENV_DIR..."
    python -m venv "$VENV_DIR"
else
    echo "[1/6] Using existing venv at $VENV_DIR"
fi

if [ -f "$VENV_DIR/Scripts/activate" ]; then
    # shellcheck disable=SC1091
    source "$VENV_DIR/Scripts/activate"   # Windows venv layout
else
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"       # POSIX venv layout
fi

echo "[2/6] Installing Python dependencies..."
pip install -q -r requirements.txt

if [ ! -f "$CLIP" ]; then
    echo "[3/6] Generating synthetic test clip at $CLIP..."
    python scripts/generate_synthetic_clip.py --output "$CLIP"
else
    echo "[3/6] Synthetic clip already exists at $CLIP (skipping generation)"
fi

echo "[4/6] Running the offline reconstruction pipeline"
echo "      (real feature matching, real triangulation, real RANSAC plane fitting -- takes roughly 1-2 minutes)..."
PYTHONPATH="$REPO_ROOT/src" python -m visionforge.cli reconstruct \
    --video "$CLIP" --output "$RUN_DIR" --input-type synthetic --no-viewer --persist

echo "[5/6] Starting the API server on http://localhost:8000 ..."
PYTHONPATH="$REPO_ROOT/src" nohup uvicorn visionforge.api.app:app --host 127.0.0.1 --port 8000 \
    > "$REPO_ROOT/.demo_api.log" 2>&1 &
API_PID=$!
echo "      API PID: $API_PID (log: .demo_api.log)"
sleep 2

echo "[6/6] Installing frontend dependencies, building, and starting the dev server on http://localhost:5173 ..."
cd "$REPO_ROOT/frontend"
npm ci
npm run build
nohup npm run dev -- --port 5173 > "$REPO_ROOT/.demo_frontend.log" 2>&1 &
FRONTEND_PID=$!
echo "      Frontend PID: $FRONTEND_PID (log: .demo_frontend.log)"
cd "$REPO_ROOT"

cat <<EOF

Demo is running:
  API:            http://localhost:8000
  API docs:       http://localhost:8000/docs
  Frontend:       http://localhost:5173
  Persisted run:  $RUN_DIR (session id: demo)

Stop both servers with:
  kill $API_PID $FRONTEND_PID
EOF
