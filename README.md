# Dynamo KV-Router A/B Experiment

An A/B benchmark of NVIDIA Dynamo's KV-aware router vs round-robin
routing, on identical multi-worker aggregated deployments, driven by a real
production trace (Mooncake) and profiled with a custom observability stack
(inferscope) on top of NVIDIA's own AIPerf methodology.

**Setup:** Qwen3-8B on vLLM 0.20.1, Dynamo container `vllm-runtime:1.2.0`,
8×A100-SXM4-40GB.

**Result:** the KV router trades completeness for latency near saturation. At
N = 2 it cuts TTFT p50 from 12125 ms to 2634 ms by rejecting 14.3% of requests
with HTTP 503; at N = 4 and 8 neither arm fails a request and the KV router's
TTFT p50 is higher (411 vs 312 ms, 339 vs 197 ms). Full table in `ANALYSIS.md`.

## What this is
- **Method**: two deployments differing ONLY in `--router-mode` (round-robin vs kv),
  same worker count, deterministic KV hashing, warm-up + 3 averaged runs.
- **Workload**: Mooncake arxiv trace (real shared-prefix structure; the case where
  KV routing matters). Filtered to inputs <= 16384 tokens
  (21,167 of 23,608 requests, 89.7% of the trace), then sliced to 1,000.
- **Measurement**: AIPerf for client-side latency/throughput; inferscope
  `--sample-only` for server-side per-device GPU truth (SM/VRAM/power) that the
  NVIDIA A/B guide does not show.
- **Evidence chain, as run**: AIPerf client metrics and per-request records,
  inferscope per-device GPU telemetry, and the Dynamo source at the container's
  tag (`v1.2.0`); see `ANALYSIS.md`. The AIConfigurator comparison in the
  original plan was not made: AIPerf replays the trace's own arrival timestamps
  and ignores `--concurrency`, so a concurrency sweep does not apply to this run
  (`RUNBOOK.md`, fixed-schedule note), and no AIConfigurator output is committed.

## Status
Executed on 8×A100-SXM4-40GB (Lambda): N = 2, 4 and 8 workers, router off and
on, a warm-up plus 3 measured runs per cell. Results in `results/`, analysis
in `ANALYSIS.md`. Under saturation (N = 2) the KV router sheds about 14% of
requests with HTTP 503; at N = 4 and 8 neither arm fails a request.

## Layout
- `RUNBOOK.md` — the full end-to-end procedure, phase by phase.
- `scripts/arm_common.sh` — shared launcher; router mode is the single A/B variable.
- `scripts/arm_off.sh`, `scripts/arm_on.sh` — the two arms (round-robin vs kv).
- `ANALYSIS.md` — results, evidence chain, rejected hypotheses and caveats.
- `results/` — AIPerf exports and inferscope JSON for each N, arm and run.
- `scripts/*.py` — trace filtering, cache warm-up and the analysis scripts.
