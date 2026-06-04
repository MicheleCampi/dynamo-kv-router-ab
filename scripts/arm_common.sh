#!/bin/bash
# Common launcher for both A/B arms. The ONLY difference between OFF and ON
# is ROUTER_MODE, passed as $1. Everything else (workers, ports, model, KV
# events) is identical by construction, so the A/B isolates routing alone.
#
# Usage: arm_common.sh <round-robin|kv> [N_WORKERS]
set -e
trap 'echo Cleaning up...; kill 0' EXIT

ROUTER_MODE="${1:?usage: arm_common.sh <round-robin|kv> [N_WORKERS]}"
N_WORKERS="${2:-2}"

# Deterministic KV hashing across all worker processes (required for KV routing).
export PYTHONHASHSEED=0

MODEL="${MODEL:-Qwen/Qwen3-8B}"
BLOCK_SIZE="${BLOCK_SIZE:-64}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-16384}"

echo "=== Launching arm: router-mode=$ROUTER_MODE, workers=$N_WORKERS, model=$MODEL ==="

# Frontend: router mode is the single A/B variable.
# --router-reset-states only meaningful for kv; harmless flag kept out of round-robin.
if [ "$ROUTER_MODE" = "kv" ]; then
    python -m dynamo.frontend --router-mode kv --router-reset-states &
else
    python -m dynamo.frontend --router-mode "$ROUTER_MODE" &
fi

# Workers: identical in BOTH arms. Each on its own GPU, system port, ZMQ endpoint.
# Workers publish KV events in both arms; only the frontend decides whether to
# consume them for routing. This keeps worker behavior identical across arms.
for (( i=0; i<N_WORKERS; i++ )); do
    DYN_SYSTEM_PORT=$(( 8081 + i )) \
    VLLM_NIXL_SIDE_CHANNEL_PORT=$(( 20097 + i )) \
    CUDA_VISIBLE_DEVICES=$i python3 -m dynamo.vllm \
        --model "$MODEL" \
        --block-size "$BLOCK_SIZE" \
        --max-model-len "$MAX_MODEL_LEN" \
        --enforce-eager \
        --kv-events-config '{"publisher":"zmq","topic":"kv-events","endpoint":"tcp://*:'$(( 20080 + i ))'","enable_kv_cache_events":true}' &
done

# Exit if any process dies; trap tears down the rest.
wait
