#!/usr/bin/env bash
set -e

echo "============================================"
echo "  StockAgent Demo - Starting..."
echo "============================================"

# Install backend deps
echo "[1/3] Installing backend dependencies..."
pip3 install -r backend/requirements.txt -q

# Install frontend deps
echo "[2/3] Installing frontend dependencies..."
if [ ! -d "frontend/node_modules" ]; then
  cd frontend && npm install --prefer-offline && cd ..
fi

# Start backend
echo "[3/3] Starting backend on port 8000..."
python3 -m uvicorn backend.main:app --port 8000 --host 0.0.0.0 &
BACKEND_PID=$!
sleep 2

# Cleanup on exit
trap "echo Stopping...; kill $BACKEND_PID 2>/dev/null; exit" INT TERM

echo ""
echo "============================================"
echo "  StockAgent running at: http://localhost:5173"
echo "============================================"
echo ""
echo "Press Ctrl+C to stop."

cd frontend && npm run dev
