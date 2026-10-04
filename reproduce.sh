#!/usr/bin/env bash
# ==============================================================================
# ThreadWeave — Production FDB-v3 Benchmark Reproduction Suite (Linux / macOS)
# Enterprise Full-Duplex Interruptible Real-Time Agent Platform
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "==========================================================================="
echo "  🏆 ThreadWeave FDB-v3 End-to-End Reproduction"
echo "==========================================================================="

# 1. Environment & API Keys Check
echo "--> 1. Verifying Environment & API Credentials..."
if [ -f ".env.local" ]; then
    export $(grep -v '^#' .env.local | xargs)
fi

: "${OPENAI_API_KEY:?Error: OPENAI_API_KEY must be set in environment or .env.local}"
: "${LIVEKIT_URL:?Error: LIVEKIT_URL must be set in environment or .env.local}"
: "${LIVEKIT_API_KEY:?Error: LIVEKIT_API_KEY must be set in environment or .env.local}"
: "${LIVEKIT_API_SECRET:?Error: LIVEKIT_API_SECRET must be set in environment or .env.local}"
echo "✅ All required API keys verified."

# 2. Virtual Environment Setup
echo "--> 2. Setting up Python environment..."
if ! command -v uv &> /dev/null; then
    pip install uv
fi

if [ ! -d ".venv_fdb" ]; then
    echo "Creating Python 3.10 virtual environment..."
    uv venv .venv_fdb --python 3.10
fi

source .venv_fdb/bin/activate
uv pip install -r requirements_livekit.txt

# 3. Dataset Extraction
echo "--> 3. Verifying Benchmark Dataset..."
BENCH_DIR="$SCRIPT_DIR/Full-Duplex-Bench/v3"
DATA_DIR="$BENCH_DIR/fdb_v3_data_released"

if [ ! -d "$DATA_DIR" ] || [ -z "$(ls -A "$DATA_DIR")" ]; then
    if [ -f "$BENCH_DIR/fdb_v3_data.zip" ]; then
        echo "Extracting $BENCH_DIR/fdb_v3_data.zip..."
        unzip -q "$BENCH_DIR/fdb_v3_data.zip" -d "$BENCH_DIR/"
    elif [ -f "$SCRIPT_DIR/fdb_v3_data.zip" ]; then
        echo "Extracting $SCRIPT_DIR/fdb_v3_data.zip..."
        unzip -q "$SCRIPT_DIR/fdb_v3_data.zip" -d "$BENCH_DIR/"
    else
        echo "⚠️ Benchmark dataset not found. Please place fdb_v3_data.zip into $BENCH_DIR/"
        exit 1
    fi
fi
echo "✅ Benchmark dataset ready."

# 4. Start LiveKit ThreadWeave Agent
echo "--> 4. Launching ThreadWeave Voice Agent..."
python lk_threadweave_agent.py dev &
AGENT_PID=$!
echo "✅ Agent started in background (PID=$AGENT_PID). Waiting 8s for WebRTC..."
sleep 8

# Trap to kill agent on script exit or failure
trap "kill -9 $AGENT_PID 2>/dev/null || true" EXIT

# 5. Run Batch Inference
echo "--> 5. Running FDB-v3 Batch Inference..."
cd "$BENCH_DIR"
python run_tool_benchmark_all_released.py --provider threadweave

# 6. Run LLM Evaluation
echo "--> 6. Running LLM Judge Evaluation (GPT-4o)..."
python evaluate_tool_calls.py \
    --benchmark benchmark_data_v2.json \
    --results-dir fdb_v3_data_released \
    --provider threadweave \
    --output "$SCRIPT_DIR/threadweave_evaluation_report.json" \
    --use-llm

# 7. Run Strict Pass-Rate Evaluation
echo "--> 7. Running Strict Pass-Rate Evaluation..."
python evaluate_pass_rate.py \
    --benchmark benchmark_data_v2.json \
    --results-dir fdb_v3_data_released \
    --provider threadweave \
    --output "$SCRIPT_DIR/threadweave_pass_rate_report.json" \
    --use-llm

echo "==========================================================================="
echo "  🏆 Reproduction Finished Successfully! Results saved to:"
echo "     $SCRIPT_DIR/threadweave_evaluation_report.json"
echo "==========================================================================="
