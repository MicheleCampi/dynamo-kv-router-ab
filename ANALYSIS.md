# Analysis — Dynamo KV-Router A/B Scaling Curve

**Setup:** 8×A100-SXM4-40GB (Lambda). Dynamo container `vllm-runtime:1.2.0`,
vLLM 0.20.1, Qwen3-8B, `--block-size 64 --max-model-len 16384 --enforce-eager`.
Workload: Mooncake trace (prefill-heavy), filtered to ISL≤16384 (21,167 reqs),
sliced to 1,000. Driver: AIPerf `--fixed-schedule --fixed-schedule-auto-offset`,
3 measured runs per cell. Server-side: inferscope `--sample-only --gpu` (per-device NVML).
Arms differ ONLY in `--router-mode`: `round-robin` (OFF) vs `kv --router-reset-states` (ON).

## Headline result

The KV-router is NOT simply "faster". Under saturation it performs **load-shedding**:
it sheds ~14% of requests (HTTP 503) to keep latency low for the rest. Round-robin
admits everything and lets latency collapse. This is a **latency-vs-completeness
trade-off**, and it only appears near saturation — it vanishes as capacity grows.

## Numbers (3 runs aggregated per cell; TTFT in ms, on COMPLETED requests)

| N | arm | sent | completed | failed | fail% | TTFT p50 | TTFT avg | 503s |
|---|-----|------|-----------|--------|-------|----------|----------|------|
| 2 | off | 3000 | 3000 | 0   | 0.0%  | 12125 | 16946 | 0   |
| 2 | on  | 3000 | 2571 | 429 | 14.3% | 2634  | 4541  | 429 |
| 4 | off | 3000 | 3000 | 0   | 0.0%  | 312   | 520   | 0   |
| 4 | on  | 3000 | 3000 | 0   | 0.0%  | 411   | 585   | 0   |
| 8 | off | 3000 | 3000 | 0   | 0.0%  | 197   | 373   | 0   |
| 8 | on  | 3000 | 3000 | 0   | 0.0%  | 339   | 443   | 0   |

Per-run failure counts at N=2/on: 103, 149, 177 (10.3% → 14.9% → 17.7%).

## Evidence chain (four independent levels)

1. **Client metrics (AIPerf):** at N=2, ON's TTFT p50 is 2.6s vs OFF's 12.1s — but
   ON completes 85.7% vs OFF's 100%. The latency advantage is partly survivorship:
   the 429 shed requests carry no TTFT and don't inflate ON's average.
2. **Temporal dynamics (per-request jsonl):** at N=2 OFF, TTFT grows monotonically
   per decile (746ms → 39,101ms) — a classic unbounded queue under saturation.
   ON stays bounded (peaks ~13s, dips when the queue drains) — it never collapses.
3. **Explicit cause (error field):** the 429 failures are HTTP 503
   `"ResourceExhausted: All workers are busy, please retry later"`, `request_ack_ns`
   absent, `request_end_ns==request_start_ns`. Concentrated at 69-92% of the run
   (the saturation window). Systematic across all 3 runs; ZERO in every other cell.
4. **Mechanism, traced to source (Dynamo v1.2.0):**
   - `--router-mode kv` creates a `KvWorkerMonitor` (`lib/llm/src/discovery/watcher.rs:806`)
     that tracks worker busy-state and feeds it to the PushRouter via `update_free_instances`.
   - The router is built with `fault_detection_enabled=true`
     (`from_client_with_monitor`, `push_router.rs`).
   - Under saturation `instance_ids_free()` is empty → the router rejects with 503
     (`push_router.rs:809-828`).
   - `--router-mode round-robin` does NOT create the monitor → workers never appear
     "busy" → no rejection → requests queue instead.
   - Divergence is gated solely on `--router-mode`; all other params at defaults.
     Verifiable by anyone at tag `v1.2.0`.

## Scaling-curve reading

The KV-router's benefit is NOT constant in N — it inverts:
- **N=2 (saturated):** large TTFT gain for admitted requests, at the cost of 14% shed.
- **N=4, N=8 (not saturated):** zero failures either arm; KV gives no benefit and a
  small TTFT overhead (e.g. p50 339ms vs 197ms at N=8) from affinity routing.
Crossover between N=2 and N=4: the point where the system stops being capacity-bound.

## Hypotheses TESTED AND REJECTED (kept for honesty)

- **"KV-router imbalances GPU load."** inferscope per-device utilization skew is
  marginal (ON/OFF stddev ratio 1.4–1.7×, absolute 2.0 vs 2.7 pp). Does NOT explain
  the TTFT effect. Rejected as primary mechanism.
- **"worker_id in AIPerf shows backend imbalance."** `worker_id` is client-side
  (always 32 regardless of N) — AIPerf's load-gen workers, not backend GPUs.
  Useless for backend load. Rejected.
- **"503 comes from kv-router's max_queued_isl_tokens backpressure."** That path
  emits `"router backpressure: queued_isl_tokens=..."`. Our 503 message is the bare
  `"All workers are busy"` → it comes from the generic `empty_free_pool_error`
  (busy-detection gate), not the tier backpressure. Rejected (wrong code path).

## Caveats (honest limits)

- Source read at tag `v1.2.0` (the container that produced the data). A separate
  `dynamo-src` checkout was `main`/1.3.0; not used for claims.
- Server-side root cause of the 503 burst (worker logs) not captured — the instance
  was ephemeral. We assert the *client-observed* 503 and the *code path*, not the
  per-worker internal state at failure time.
- `--router-reset-states` was passed only on the ON arm (it's KV-specific). Failure
  rate rises across the 3 ON runs (10→18%); not isolated whether reset-states or
  accumulated pressure drives this. Flagged, not claimed.
