# Dynamo KV-Router A/B Experiment

A rigorous A/B benchmark of NVIDIA Dynamo's KV-aware router vs round-robin
routing, on identical multi-worker aggregated deployments, driven by a real
production trace (Mooncake) and profiled with a custom observability stack
(inferscope) on top of NVIDIA's own AIPerf methodology.

## What this is
- **Method**: two deployments differing ONLY in `--router-mode` (round-robin vs kv),
  same worker count, deterministic KV hashing, warm-up + 3 averaged runs.
- **Workload**: Mooncake arxiv trace (real shared-prefix structure; the case where
  KV routing matters). Filtered to inputs <= 16384 tokens (89.7% of the trace).
- **Measurement**: AIPerf for client-side latency/throughput; inferscope
  `--sample-only` for server-side per-device GPU truth (SM/VRAM/power) that the
  NVIDIA A/B guide does not show.
- **Triangulation**: AIConfigurator predicted vs AIPerf measured vs inferscope
  resource-observed.

## Status
Cold preparation complete (see RUNBOOK.md). Execution pending on a rented
multi-GPU instance. This repo holds the runbook, the A/B launch scripts, and
(once run) the analysis.

## Layout
- `RUNBOOK.md` — the full end-to-end procedure, phase by phase.
- `scripts/arm_common.sh` — shared launcher; router mode is the single A/B variable.
- `scripts/arm_off.sh`, `scripts/arm_on.sh` — the two arms (round-robin vs kv).
