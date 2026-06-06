import json, statistics as st
from collections import Counter, defaultdict

def load_requests(N, arm, r):
    reqs=[]
    with open(f"results/N{N}/{arm}/run_{r}/profile_export.jsonl") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            d=json.loads(line)
            m=d.get("metadata",{}); met=d.get("metrics",{})
            if m.get("benchmark_phase")!="profiling": continue
            if m.get("was_cancelled"): continue
            ttft=met.get("time_to_first_token",{}).get("value")
            reqs.append({
                "start_ns": m.get("request_start_ns"),
                "worker": m.get("worker_id"),
                "conv": m.get("conversation_id"),
                "ttft": ttft,
                "isl": met.get("input_sequence_length",{}).get("value"),
            })
    return reqs

print("=== PARTE 1: distribuzione carico per-worker (run_1) ===")
print(f"{'N':>2} {'arm':>4} | {'#req':>5} | {'#worker':>7} | {'req/worker (min..max)':>22} | {'imbalance(maxδmean)':>18}")
print("-"*80)
for N in (2,4,8):
    for arm in ("off","on"):
        reqs=load_requests(N,arm,1)
        c=Counter(r["worker"] for r in reqs if r["worker"])
        counts=sorted(c.values())
        if not counts: 
            print(f"{N:>2} {arm:>4} | nessun worker_id"); continue
        mean=st.mean(counts)
        imbalance=(max(counts)-mean)/mean*100 if mean else 0
        print(f"{N:>2} {arm:>4} | {len(reqs):>5} | {len(c):>7} | {min(counts):>9}..{max(counts):<10} | {imbalance:>16.1f}%")
