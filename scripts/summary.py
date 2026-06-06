import json, statistics as st

def per_request(N,arm,r):
    rows=[]
    for line in open(f"results/N{N}/{arm}/run_{r}/profile_export.jsonl"):
        line=line.strip()
        if not line: continue
        d=json.loads(line); m=d["metadata"]; met=d["metrics"]
        err=d.get("error")
        ttft=met.get("time_to_first_token",{}).get("value")
        failed = (err is not None) or (ttft is None) or (not m.get("request_ack_ns"))
        rows.append({"failed":failed,"ttft":ttft,"start":m.get("request_start_ns"),
                     "code": (err or {}).get("code")})
    return rows

print("="*70)
print("DYNAMO KV-ROUTER A/B — SCALING CURVE SUMMARY (8x A100, v1.2.0)")
print("="*70)
print(f"\n{'N':>2} {'arm':>4} | {'sent':>5} {'compl':>6} {'fail':>5} {'fail%':>6} | {'TTFT p50':>9} {'TTFT avg':>9} | {'503s':>5}")
print("-"*72)
for N in (2,4,8):
    for arm in ("off","on"):
        sent=comp=fail=n503=0; ttfts=[]
        for r in (1,2,3):
            for row in per_request(N,arm,r):
                sent+=1
                if row["failed"]:
                    fail+=1
                    if row["code"]==503: n503+=1
                else:
                    comp+=1; ttfts.append(row["ttft"])
        p50=st.median(ttfts) if ttfts else 0
        avg=st.mean(ttfts) if ttfts else 0
        print(f"{N:>2} {arm:>4} | {sent:>5} {comp:>6} {fail:>5} {100*fail/sent:>5.1f}% | {p50:>8.0f}m {avg:>8.0f}m | {n503:>5}")
print("\nNote: TTFT in ms, su richieste COMPLETATE (le fallite non hanno TTFT).")
print("I 503 sono 'ResourceExhausted: All workers are busy' — solo N=2/on.")
