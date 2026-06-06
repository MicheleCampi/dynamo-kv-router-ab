import json, statistics as st

def load(N,arm,r):
    reqs=[]
    for line in open(f"results/N{N}/{arm}/run_{r}/profile_export.jsonl"):
        line=line.strip()
        if not line: continue
        d=json.loads(line); m=d["metadata"]; met=d["metrics"]
        if m.get("benchmark_phase")!="profiling" or m.get("was_cancelled"): continue
        ttft=met.get("time_to_first_token",{}).get("value")
        if ttft is None or m.get("request_start_ns") is None: continue
        reqs.append((m["request_start_ns"], ttft))
    reqs.sort()
    return reqs

print("=== N=2: TTFT p50 per decile temporale (run_1) — se cresce monotono = coda ===")
for arm in ("off","on"):
    reqs=load(2,arm,1)
    n=len(reqs); dec=n//10
    print(f"\n-- N=2 {arm} ({n} req) --")
    vals=[]
    for i in range(10):
        chunk=reqs[i*dec:(i+1)*dec] if i<9 else reqs[i*dec:]
        med=st.median([x[1] for x in chunk])
        vals.append(med)
        bar="#"*int(med/1000)
        print(f"  decile {i+1:>2}: TTFT p50 {med:>8.0f}ms {bar}")
