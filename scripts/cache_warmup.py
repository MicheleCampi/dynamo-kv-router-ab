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
        reqs.append((m["request_start_ns"], ttft, met.get("input_sequence_length",{}).get("value")))
    reqs.sort(key=lambda x:x[0])
    return reqs

print("=== Cache warm-up: TTFT mediano primo 20% vs ultimo 20% delle richieste (ordinate per arrivo), media sui 3 run ===")
print(f"{'N':>2} {'arm':>4} | {'TTFT p50 primi20%':>17} | {'TTFT p50 ultimi20%':>18} | {'variazione':>10}")
print("-"*70)
for N in (2,4,8):
    for arm in ("off","on"):
        firsts=[]; lasts=[]
        for r in (1,2,3):
            reqs=load(N,arm,r)
            if len(reqs)<10: continue
            k=max(1,len(reqs)//5)
            firsts.append(st.median([x[1] for x in reqs[:k]]))
            lasts.append(st.median([x[1] for x in reqs[-k:]]))
        if not firsts: continue
        f=st.mean(firsts); l=st.mean(lasts)
        chg=100*(l-f)/f if f else 0
        print(f"{N:>2} {arm:>4} | {f:>15.0f}ms | {l:>16.0f}ms | {chg:>+9.1f}%")
