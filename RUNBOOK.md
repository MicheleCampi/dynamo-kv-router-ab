# Dynamo KV-Router A/B Experiment — Runbook

## Objective
Quantify the effect of Dynamo's KV-aware router vs round-robin routing on a
workload with shared prompt prefixes, on identical multi-worker aggregated
deployments. Measure with AIPerf (latency/throughput) AND inferscope (GPU/process
resource profiling — the distinctive angle). Compare against AIConfigurator predictions.

## Method (rigor requirements)
- A/B differs ONLY in router mode: round-robin (OFF) vs kv (ON). SAME worker count both arms.
- PYTHONHASHSEED=0 on all vLLM processes (deterministic KV hashing — confirmed in NVIDIA's own agg_router.sh).
- KV events via ZMQ, discovery via file: NO etcd/NATS needed on single multi-GPU host.
- Mooncake trace dataset (realistic shared prefixes; ~50% cache-hit ratio).
- 3+ runs per arm, averaged, for statistical significance.
- Warm-up run before measurement. Document cluster state and any anomalies.
- Equal worker health verified before each benchmark.

## Hardware target
- Lambda on-demand multi-GPU instance (NOT managed K8s — that requires 2-week min commit, out of budget).
- Minimum 2 GPU (base A/B); 4 GPU preferred for cleaner signal.
- Est. cost: ~$2.6-10/hr depending on GPU count/type. Budget cap: 50 EUR.

## Cost discipline
- ALL setup/scripts prepared and dry-validated on the Hetzner VM (CPU) BEFORE provisioning GPU.
- GPU instance powered on ONLY when runbook is complete and scripts staged.
- Teardown immediately after data collection. No idle GPU time.

----------------------------------------------------------------------

## Phase 1: Provision and verify GPU instance

1. Launch Lambda on-demand instance (2x or 4x A100/A10, Ubuntu 22.04/24.04, CUDA 12.9+).
2. SSH in. Verify GPU + driver:
       nvidia-smi
       (confirm driver >= 575 for CUDA 12, N GPUs visible)
3. Verify Docker + NVIDIA container runtime:
       docker info | grep -i runtime
       docker run --rm --gpus all nvidia/cuda:12.9.0-base-ubuntu22.04 nvidia-smi

## Phase 2: Pull Dynamo container

       docker pull nvcr.io/nvidia/ai-dynamo/vllm-runtime:1.2.0

Start container with GPUs, host network, shared dir:
       docker run --gpus all --network host -it -v ~/dynamo-ab:/work --shm-size 16g nvcr.io/nvidia/ai-dynamo/vllm-runtime:1.2.0 bash

Notes:
- --shm-size 16g required for vLLM IPC.
- --network host so frontend:8000 and ZMQ ports are reachable.
- /work holds launch scripts, dataset, and output artifacts (persisted on host).

## Phase 3: Smoke test (single worker, minimal cost)

Confirm Dynamo serves before the A/B:
       cd /work
       python -m dynamo.frontend > fe.log 2>&1 &
       CUDA_VISIBLE_DEVICES=0 python3 -m dynamo.vllm --model Qwen/Qwen3-8B --enforce-eager --max-model-len 4096 > w0.log 2>&1 &
       (wait for ready, then:)
       curl -s localhost:8000/v1/chat/completions -H 'Content-Type: application/json' -d '{"model":"Qwen/Qwen3-8B","messages":[{"role":"user","content":"hi"}],"max_tokens":16}'
       (expect valid completion; then kill these before the A/B)

----------------------------------------------------------------------

## Phase 4: The two A/B arms (rigor-critical)

KEY RIGOR POINT: both arms use the SAME worker count. Only the frontend
--router-mode differs. Do NOT use agg.sh (1 worker) as the OFF arm — that
would compare different topologies, invalidating the result.

We stage two scripts in /work, derived from NVIDIA's agg_router.sh but with
worker count = N (start N=2, scale to 4 if instance has 4 GPUs) and a
parameterized router mode.

Shared by both arms:
- export PYTHONHASHSEED=0   (deterministic KV hashing, required)
- MODEL=Qwen/Qwen3-8B  BLOCK_SIZE=64
- each worker on its own CUDA_VISIBLE_DEVICES, own DYN_SYSTEM_PORT, own ZMQ endpoint
- workers identical across both arms

OFF arm (arm_off.sh): frontend with --router-mode round-robin
ON  arm (arm_on.sh):  frontend with --router-mode kv --router-reset-states

Frontend line differs ONLY by router mode:
       OFF:  python -m dynamo.frontend --router-mode round-robin &
       ON:   python -m dynamo.frontend --router-mode kv --router-reset-states &

Worker line (identical in both arms), repeated per GPU index i = 0..N-1:
       DYN_SYSTEM_PORT=$((8081+i)) CUDA_VISIBLE_DEVICES=$i python3 -m dynamo.vllm --model $MODEL --block-size $BLOCK_SIZE --enforce-eager --kv-events-config '{"publisher":"zmq","topic":"kv-events","endpoint":"tcp://*:'$((20080+i))'","enable_kv_cache_events":true}' &

Note: even the OFF arm publishes KV events (workers identical); the frontend
simply does not consume them for routing. This keeps worker behavior identical
so the ONLY variable is routing. Verify all N workers register before benchmarking.

We will write arm_off.sh and arm_on.sh as actual files in a later step,
parameterized by N, once the worker count is fixed to the rented instance.

----------------------------------------------------------------------

## Phase 5: Mooncake dataset (realistic shared prefixes)

WHY: KV routing only helps when requests share prefixes. Random synthetic data
shows <5% gain (per NVIDIA A/B guide). Mooncake = real arxiv production trace,
privacy-preserving block hashes, ~50% cache-hit ratio. This is what makes the
experiment meaningful rather than a null result.

Mooncake trace source (public):
       https://raw.githubusercontent.com/kvcache-ai/Mooncake/refs/heads/main/FAST25-release/arxiv-trace/mooncake_trace.jsonl

Download on the GPU box (small file, into /work):
       cd /work
       curl -sL -o mooncake_trace.jsonl <URL above>
       wc -l mooncake_trace.jsonl   (sanity: expect thousands of lines)
       head -1 mooncake_trace.jsonl  (inspect schema: timestamp, input_length, output_length, hash_ids)

The trace gives per-request: arrival timestamp, input/output lengths, and
block hash_ids encoding shared prefixes. AIPerf replays it preserving the
prefix-sharing structure (the cache-hit pressure that exercises the router).

DECISION (to fix before running): use a trimmed slice for cost control.
The full trace can be long; we will cap to the first K requests (e.g. 1000)
so each A/B run is minutes, not hours. Same slice for both arms (identical input).

Prep step (trim + verify), prepared cold here, run on box:
       head -1000 mooncake_trace.jsonl > mooncake_1k.jsonl
       wc -l mooncake_1k.jsonl   (expect 1000)

----------------------------------------------------------------------

## Phase 6: Benchmark execution with AIPerf

AIPerf replays the Mooncake trace against the frontend (localhost:8000),
preserving prefix structure. Run identically against each arm.

Per-arm procedure (do OFF first, then ON, or interleave — document order):
1. Start the arm (arm_off.sh or arm_on.sh). Wait until all N workers register
   (check frontend log / curl a test request returns 200).
2. WARM-UP run (not measured): one full pass to populate KV caches.
       (warm-up is mandatory: a cold cache hides the routing benefit)
3. THREE measured runs, saved to separate artifact dirs.
4. Tear down the arm cleanly (kill 0 / trap), then start the other arm.

AIPerf command (mooncake trace replay), per measured run r=1..3:
       aiperf profile --model Qwen/Qwen3-8B --tokenizer Qwen/Qwen3-8B --endpoint-type chat --streaming -u http://localhost:8000 --input-file mooncake_1k.jsonl --custom-dataset-type mooncake_trace --artifact-dir /work/results/<arm>/run_${r} --random-seed $((100+r))

Key flags rationale:
- --input-file + --custom-dataset-type mooncake_trace: replay the real trace (not synthetic).
- --random-seed varied per run: independent samples for averaging.
- same command for both arms: only the running deployment differs.

Metrics AIPerf reports (the A/B comparison surface):
- TTFT (mean, p50, p95, p99)   <- KV routing should improve this most
- ITL / inter-token latency
- request latency
- output token throughput (tokens/s)
- request throughput (req/s)

Expected (per NVIDIA guide, prefix-heavy workload): 20-50% TTFT improvement
with KV routing; throughput gain smaller (single-digit %). A <5% TTFT delta
would indicate insufficient prefix sharing in the slice — investigate, do not
fabricate a result.

----------------------------------------------------------------------

## Phase 7: Distinctive profiling layer (inferscope + eBPF probe)

THIS IS THE TOP-5% DIFFERENTIATOR. The NVIDIA A/B guide measures client-side
latency/throughput only. We add server-side resource truth that the guide does
NOT show: what the GPUs and worker processes actually do under each routing mode.
Nobody else pairs the NVIDIA methodology with a custom profiling stack.

The hypothesis to test with our own tools:
- KV routing concentrates prefix-sharing requests on fewer workers -> expect
  UNEVEN per-GPU utilization vs round-robin's even spread.
- KV routing avoids re-prefill -> expect lower aggregate SM-active time and
  fewer prefill-shaped compute bursts for the same workload.
- KV cache reuse -> different VRAM occupancy pattern across workers.

Tooling placement (run DURING each measured AIPerf run):

(a) inferscope per-GPU sampling — capture per-device SM util, VRAM, power across
    all N GPUs for the duration of the run. One sampler covering all devices.
       (inferscope already does per-device NVML sampling; point it at the box
        and tag the output with arm + run number)

(b) Optional eBPF probe — if attaching to the worker processes is feasible
    inside the container, trace CUDA-driver activity (cuLaunchKernel volume,
    memory ops) per worker. This shows the re-prefill avoidance at kernel level.
       (probe needs CAP_BPF/privileged container + kernel BTF; verify feasibility
        in smoke phase. If the container blocks eBPF, document as a limitation
        and rely on inferscope NVML sampling alone — still distinctive.)

Output to correlate in the article:
- AIPerf client metrics (TTFT/throughput) per arm
- inferscope per-GPU SM/VRAM/power distribution per arm (the server-side story)
- AIConfigurator predicted numbers (predicted vs measured)
THREE-WAY comparison: predicted (AIC) vs client-observed (AIPerf) vs
resource-truth (inferscope). That triangulation is the publishable insight.

NOTE on power: AIConfigurator returned 0.0 W for vLLM (no power data in its DB).
inferscope MEASURES real power via NVML. So the article can show a number AIC
structurally cannot predict — a concrete demonstration of why the profiler matters.

### Phase 7 — concrete commands (inferscope --sample-only, now implemented)

inferscope now has `--sample-only` (committed, ADR-009): it attaches to a PID and
samples CPU/RSS + per-device GPU for a fixed duration WITHOUT generating load, so
it composes with AIPerf instead of competing with it. Build on the box with the
gpu feature:
       cargo build --release --features gpu-nvidia
       (binary: target/release/inferscope)

Identify the worker PIDs after starting an arm (frontend + N workers):
       pgrep -af "dynamo.vllm" | cat
       (each worker is one python process bound to one CUDA_VISIBLE_DEVICES)

Two sampling strategies, decide before the run:

STRATEGY A (one sampler, all GPUs) — simplest, matches the per-device hypothesis:
  inferscope's --gpu samples EVERY visible NVIDIA device each tick. One inferscope
  process therefore captures per-device SM/VRAM/power for all N GPUs at once. The
  --pid here is just to anchor a process resource section; point it at one worker
  (or the frontend). Run it for the AIPerf run's duration:
       DUR=<seconds matching the AIPerf run>
       ./target/release/inferscope --sample-only \
         --pid <one_worker_pid> --duration-secs $DUR \
         --gpu --sample-period-ms 100 --json \
         > results/<arm>/inferscope_run<r>.json
  The per_device array in the JSON gives the per-GPU breakdown -> directly tests
  "KV routing skews load across GPUs" (ON) vs "round-robin spreads evenly" (OFF).

STRATEGY B (one sampler per worker) — adds per-PROCESS CPU/RSS per worker:
  Launch one inferscope per worker PID (only one needs --gpu to avoid duplicate
  GPU sampling). More artifacts, finer process attribution. Use only if per-worker
  CPU/RSS matters for the story; otherwise Strategy A is enough.

TIMING: start inferscope at the SAME moment as the measured AIPerf run, with
--duration-secs slightly longer than the expected run so sampling brackets it.
Run warm-up first (unmeasured), then for each measured run r=1..3 launch AIPerf
and inferscope together.

TAGGING (decided): one JSON per arm+run at
       results/{off,on}/inferscope_run{1,2,3}.json
alongside AIPerf's results/{off,on}/run_{1,2,3}/. Arm and run are encoded in the
path; the JSON also carries pid/duration/sample_period for provenance.

SAMPLE PERIOD: 100 ms (not the 50 ms probe default) — a multi-minute sampling
window at 50 ms produces large JSON for no added insight; 100 ms is ample for
SM/VRAM/power trends over a run.

----------------------------------------------------------------------

## Phase 8: Data collection and teardown

Before killing the instance, pull EVERYTHING off the box (artifacts live in
/work on the host volume, but verify):
- /work/results/off/run_{1,2,3}/   (AIPerf artifacts, OFF arm)
- /work/results/on/run_{1,2,3}/    (AIPerf artifacts, ON arm)
- inferscope JSON outputs per arm+run
- frontend + worker logs (fe.log, w*.log) per arm
- the exact arm_off.sh / arm_on.sh used (provenance)
- nvidia-smi snapshot, driver/CUDA versions, container image digest
- the mooncake_1k.jsonl slice actually used

Copy to host then scp to Hetzner VM (or local), e.g.:
       scp -r ubuntu@<lambda-ip>:/work/results ~/dynamo-ab-experiment/results/

TEARDOWN (cost discipline — do immediately after data is safe):
1. Confirm results copied + readable off the GPU box.
2. Terminate the Lambda instance from the dashboard (not just stop — terminate
   to stop billing). Verify it disappears from the instances list.
3. Record total GPU minutes used and cost (for the budget log).

## Phase 9: Analysis and article (cold, on VM — zero cost)

Back on the VM, with results in hand:
1. Average the 3 runs per arm; compute mean + stddev for TTFT/ITL/throughput.
2. Compute the OFF->ON delta (% improvement) with variability bars.
3. Build the three-way table: AIC predicted vs AIPerf measured vs inferscope resource truth.
4. Plot per-GPU utilization distribution (OFF even vs ON skewed — the server-side story).
5. Write the article: methodology (NVIDIA-faithful), the distinctive profiling
   layer, the triangulation, honest limitations (single-node, slice size, no RDMA).

## Pre-flight checklist (before ANY GPU spend)
[ ] arm_off.sh and arm_on.sh written as real files, N fixed to instance GPU count
[ ] Mooncake URL verified reachable + schema inspected
[ ] AIPerf mooncake_trace replay flags confirmed against installed aiperf version
[ ] inferscope binary/usage staged + tagging scheme decided
[ ] eBPF-in-container feasibility known (works / documented limitation)
[ ] teardown steps clear; budget log ready

----------------------------------------------------------------------

## Findings from cold prep (verified, not assumed)

MOONCAKE URL VERIFIED reachable. Schema confirmed:
  {timestamp, input_length, output_length, hash_ids:[...]}
- hash_id 0 recurs as the first block across many requests = shared system-prompt-like prefix.
- Long identical hash_id runs (e.g. [46..57]) repeat across requests, diverging only at the tail
  = textbook prefix-sharing the KV router exploits. Confirms the workload is NOT a null-result risk.

CRITICAL ADJUSTMENT discovered from real data:
- input_length ranges ~2,000 to ~87,000 tokens (highly variable, often large).
- Our worker --max-model-len 4096 is TOO LOW: long requests would be rejected/truncated.
  ACTION: raise --max-model-len (e.g. 32768) in arm_common.sh before running, OR
  pre-filter the trace slice to requests under the chosen max-model-len.
  Trade-off: larger max-model-len = more VRAM per worker = may need bigger GPU.
- Large inputs = heavier prefill = MORE upside for KV routing (re-prefill avoidance). Good for signal.

DECISION PENDING: pick max-model-len vs trace-slice filter to balance VRAM and trace fidelity.

----------------------------------------------------------------------

## AIPerf flags verified against installed version (aiperf 0.11.0)

VALUE SYNTAX: both "mooncake-trace" and "mooncake_trace" are accepted. OK as written.

FIXED-SCHEDULE IS AUTOMATIC for trace datasets (CONFIRMED, changes protocol):
- AIPerf auto-replays the trace's real arrival timestamps; --concurrency is IGNORED.
  So the AIConfigurator-style concurrency sweep does NOT apply to a Mooncake run.
- This is MORE rigorous (real production arrival pattern), but means our A/B is
  "replay the same timestamped trace against each arm" rather than "sweep concurrency".
- Use --fixed-schedule-auto-offset so every run starts at t=0 identically (3 comparable runs).
- Optional: --fixed-schedule-start-offset / --fixed-schedule-end-offset to benchmark a
  fixed time-window slice of the trace (cleaner than head -1000 since it respects timing).

BLOCK-SIZE COHERENCE (rigor-critical, was nearly missed):
- --isl-block-size controls how AIPerf maps hash_ids -> cached blocks.
  Formula: total_prompt_len = (num_hash_ids - 1) * block_size + final_block_size.
- This is the AIPerf-side block size for SIMULATING the prompt from hash_ids. It is a
  CLIENT-side construct (how the replayed prompt is built), distinct from vLLM worker
  --block-size 64 (the engine's KV paging granularity). They need not be equal, but BOTH
  must be documented: the client block-size determines prompt content/length, the engine
  block-size determines KV cache paging. Fix and record both before the runs.

REVISED AIPerf command (trace replay, per run r=1..3):
       aiperf profile --model Qwen/Qwen3-8B --tokenizer Qwen/Qwen3-8B --endpoint-type chat --streaming -u http://localhost:8000 --input-file mooncake_1k.jsonl --custom-dataset-type mooncake_trace --fixed-schedule-auto-offset --artifact-dir /work/results/<arm>/run_${r}
       (note: --concurrency removed — ignored under fixed-schedule; timing comes from the trace)

----------------------------------------------------------------------

## DECISION: max-model-len and trace filtering (data-driven, verified)

Trace input_length distribution (full trace, 23,608 requests):
  min=890  p50=6,345  p90=16,794  p95=26,081  p99=61,623  max=125,546
  >4096: 70.5%  | >8192: 21.7% | >16384: 10.3% | >32768: 3.1% | >65536: 0.9%

CONCLUSION: original max-model-len 4096 was unusable (would drop 70.5% of trace).

DECISION (data-driven):
- FILTER the trace to input_length <= 16384 (keeps 21,167 req = 89.7% of trace).
  Filtering (not truncating): every request runs in full -> honest workload, no
  runtime truncation artifacts. Documented as "trace subset, inputs <= 16384 (89.7%)".
- Set worker --max-model-len 16384 (16384 input + up to 2000 output fits;
  max observed output = 2000, p90 = 480).
- VRAM: 16384 ctx keeps KV cache moderate -> A100 40GB or L40S likely sufficient
  (cheaper than 80GB). Confirm exact VRAM in smoke phase before committing the run.

Workload shape (filtered subset):
- PREFILL-HEAVY: output_length p50=26, p90=480, max=2000. Long inputs, short outputs.
- This is the IDEAL case for KV routing: prefill dominates cost, prefix reuse
  (re-prefill avoidance) is exactly what the router optimizes. Expect strong signal.

isl-block-size: leave at mooncake default (512) — matches how the trace hash_ids
were authored; documented, not changed. (Engine vLLM --block-size stays 64.)

Filter command (cold-prepared, run on box or VM):
       python3 -c "import json,sys
for line in open('mooncake_trace.jsonl'):
    line=line.strip()
    if not line: continue
    d=json.loads(line)
    if d['input_length']<=16384: print(line)" > mooncake_filtered.jsonl
       head -1000 mooncake_filtered.jsonl > mooncake_1k.jsonl   # slice for a short run

----------------------------------------------------------------------

## Phase 7c: eBPF probe feasibility (OPTIONAL — documented fallback)

STATUS: nice-to-have, NOT required. The core server-side story is fully covered
by inferscope --sample-only (per-device GPU SM/VRAM/power). The eBPF probe
(vllm-coldstart-probe) would ADD a kernel/CUDA-driver view: cuLaunchKernel
volume and memory-op counts per worker, showing re-prefill avoidance at the
driver level. Valuable as a bonus, but the experiment's thesis stands without it.

WHY IT MIGHT NOT WORK IN-CONTAINER:
- eBPF needs CAP_BPF (or CAP_SYS_ADMIN on older kernels) and access to kernel
  BTF (/sys/kernel/btf/vmlinux on the HOST kernel).
- The Dynamo vllm-runtime container is not guaranteed to run privileged, and a
  managed GPU host (Lambda) may not expose BTF or allow bpf() from inside it.
- This cannot be fully resolved cold; confirm on the instance during smoke phase.

FEASIBILITY CHECK (run on the instance, in the smoke phase, BEFORE relying on it):
  1. Host kernel + BTF present?
       uname -r
       ls -l /sys/kernel/btf/vmlinux   (must exist for CO-RE/aya)
  2. Can the container load a probe? Run the container with the caps eBPF needs:
       docker run --gpus all --network host --privileged \\
         -v /sys/kernel/btf:/sys/kernel/btf:ro \\
         -v ~/dynamo-ab:/work ... (rest as Phase 2)
     (--privileged is the blunt option; CAP_BPF + CAP_PERFMON is the narrow one.
      For a throwaway benchmark box, --privileged is acceptable and simplest.)
  3. Inside the container, sanity-check bpf() is allowed:
       cat /proc/sys/kernel/unprivileged_bpf_disabled  (informational)
       (the real test is loading the probe; if it attaches, eBPF works here)
  4. Build/run the probe (vllm-coldstart-probe) against a worker PID for a short
     window and confirm events are captured.

DECISION RULE:
  - If steps 1-4 succeed -> run the probe DURING measured runs, alongside
    inferscope. Tag output results/{off,on}/probe_run{1,2,3}.* .
  - If ANY step fails -> SKIP eBPF, document it as a known environment limitation
    in the article ("kernel-level tracing not available in the managed container;
    server-side analysis relies on NVML sampling via inferscope"). The experiment
    proceeds unchanged. DO NOT spend GPU time fighting container privileges.

COST DISCIPLINE: the eBPF feasibility check is a few minutes in the smoke phase
on a CHEAP single-GPU window, NOT during the paid multi-GPU A/B run. Decide
go/no-go before the expensive run so the A/B itself is never blocked by it.

======================================================================
# CONSOLIDATED EXECUTION (single source of truth)
======================================================================

The phases above are the reasoning and context. THIS section is the exact
sequence to run during the paid GPU session, with all parameters reconciled
to the decisions made later in the document (trace filter, fixed-schedule,
sample-only). When executing, follow THIS — not the per-phase snippets above,
which predate some decisions and are kept only as rationale.

## Fixed parameters (reconciled)
- MODEL = Qwen/Qwen3-8B
- N_WORKERS = 2 (or 4 if the instance has 4 GPUs) — SAME in both arms
- vLLM worker: --block-size 64, --max-model-len 16384, --enforce-eager
- AIPerf client: --isl-block-size 512 (mooncake default), --fixed-schedule-auto-offset
- Trace: filtered to input<=16384 THEN sliced. NOT head -1000 on the raw trace.
- inferscope: --sample-only, --gpu, --sample-period-ms 100
- Discovery: file backend; KV events: zmq. No etcd/NATS.

## Step 0 — instance up, container running (Phases 1-2)
Provision N-GPU instance; verify nvidia-smi; pull and run the container
(--gpus all --network host --shm-size 16g -v ~/dynamo-ab:/work). For the eBPF
option also add --privileged -v /sys/kernel/btf:/sys/kernel/btf:ro (Phase 7c).

## Step 1 — smoke test (cheap, 1 worker)
       cd /work
       python -m dynamo.frontend > fe.log 2>&1 &
       CUDA_VISIBLE_DEVICES=0 python3 -m dynamo.vllm --model Qwen/Qwen3-8B \
         --block-size 64 --max-model-len 16384 --enforce-eager > w0.log 2>&1 &
       # wait for ready, then:
       curl -s localhost:8000/v1/chat/completions -H 'Content-Type: application/json' \
         -d '{"model":"Qwen/Qwen3-8B","messages":[{"role":"user","content":"hi"}],"max_tokens":16}'
       # expect a valid completion. ALSO confirm the OFF arm flag is accepted:
       # (round-robin is a validated choice — verified in router_args.py)
       # kill the smoke processes before the A/B.

## Step 2 — prepare the dataset (filter THEN slice)
       cd /work
       curl -sL -o mooncake_trace.jsonl \
         https://raw.githubusercontent.com/kvcache-ai/Mooncake/refs/heads/main/FAST25-release/arxiv-trace/mooncake_trace.jsonl
       python3 -c "import json
[print(l.strip()) for l in open('mooncake_trace.jsonl')
 if l.strip() and json.loads(l)['input_length']<=16384]" > mooncake_filtered.jsonl
       head -1000 mooncake_filtered.jsonl > mooncake_1k.jsonl
       wc -l mooncake_1k.jsonl   # expect 1000

## Step 3 — per arm (run OFF first, then ON), ARM in {off, on}
Start the arm with N identical workers; only the frontend router mode differs.
       export PYTHONHASHSEED=0
       # frontend:
       #   OFF: python -m dynamo.frontend --router-mode round-robin > fe.log 2>&1 &
       #   ON : python -m dynamo.frontend --router-mode kv --router-reset-states > fe.log 2>&1 &
       # then N workers, i=0..N-1, IDENTICAL in both arms:
       #   DYN_SYSTEM_PORT=$((8081+i)) CUDA_VISIBLE_DEVICES=$i python3 -m dynamo.vllm \
       #     --model Qwen/Qwen3-8B --block-size 64 --max-model-len 16384 --enforce-eager \
       #     --kv-events-config '{"publisher":"zmq","topic":"kv-events","endpoint":"tcp://*:'$((20080+i))'","enable_kv_cache_events":true}' &
       # (use scripts/arm_off.sh / arm_on.sh with N as arg)
Verify ALL N workers registered before benchmarking:
       pgrep -af dynamo.vllm | cat   # expect N processes
       curl -s localhost:8000/v1/models   # model present

## Step 4 — warm-up (unmeasured), then 3 measured runs
WARM-UP (populate caches; result discarded):
       aiperf profile --model Qwen/Qwen3-8B --tokenizer Qwen/Qwen3-8B \
         --endpoint-type chat --streaming -u http://localhost:8000 \
         --input-file mooncake_1k.jsonl --custom-dataset-type mooncake_trace \
         --isl-block-size 512 --fixed-schedule-auto-offset \
         --artifact-dir /work/results/${ARM}/warmup

For r in 1 2 3 (measured): launch AIPerf and inferscope TOGETHER.
       # inferscope (background, brackets the run):
       PID=$(pgrep -f dynamo.vllm | head -1)
       ./inferscope --sample-only --pid $PID --duration-secs <run_secs+30> \
         --gpu --sample-period-ms 100 --json > /work/results/${ARM}/inferscope_run${r}.json &
       # AIPerf (foreground):
       aiperf profile --model Qwen/Qwen3-8B --tokenizer Qwen/Qwen3-8B \
         --endpoint-type chat --streaming -u http://localhost:8000 \
         --input-file mooncake_1k.jsonl --custom-dataset-type mooncake_trace \
         --isl-block-size 512 --fixed-schedule-auto-offset \
         --artifact-dir /work/results/${ARM}/run_${r}

WHY 3 runs (corrected rationale): under fixed-schedule the trace replay is
deterministic (same arrival pattern every run), so the 3 runs measure SYSTEM
variance (scheduler, cache warmth, jitter) for the SAME input — not different
statistical samples. Report mean +/- stddev across the 3. Do NOT vary a seed to
manufacture "independent samples": the trace timing is the controlled input.

## Step 5 — teardown the arm, repeat for the other arm
       # stop frontend + workers (kill the process group / Ctrl-C the script)
       # confirm GPUs idle (nvidia-smi) before starting the next arm.

## Step 6 — collect and terminate (Phase 8)
Pull /work/results off the box; record GPU minutes + cost; TERMINATE the instance.

## Step 7 — analysis + article (Phase 9, on VM, zero cost)
Average 3 runs/arm; OFF->ON delta with stddev; three-way table
(AIC predicted vs AIPerf measured vs inferscope resource truth); per-GPU
utilization distribution (OFF even vs ON skewed); write the article.
