import json, glob, statistics as st
from collections import defaultdict

def get(d, key, sub):
    v = d.get(key)
    if isinstance(v, dict):
        return v.get(sub)
    return None

# raccogli per (N, arm) i 3 run
data = defaultdict(lambda: defaultdict(list))
for N in (2,4,8):
    for arm in ("off","on"):
        for r in (1,2,3):
            f = f"results/N{N}/{arm}/run_{r}/profile_export_aiperf.json"
            try:
                d = json.load(open(f))
            except FileNotFoundError:
                print("MANCA", f); continue
            data[(N,arm)]["ttft_avg"].append(get(d,"time_to_first_token","avg"))
            data[(N,arm)]["ttft_p50"].append(get(d,"time_to_first_token","p50"))
            data[(N,arm)]["ttft_p99"].append(get(d,"time_to_first_token","p99"))
            data[(N,arm)]["itl_avg"].append(get(d,"inter_token_latency","avg"))
            data[(N,arm)]["itl_p50"].append(get(d,"inter_token_latency","p50"))
            data[(N,arm)]["req_lat_avg"].append(get(d,"request_latency","avg"))
            data[(N,arm)]["out_tok_thru"].append(get(d,"output_token_throughput","avg"))
            data[(N,arm)]["req_thru"].append(get(d,"request_throughput","avg"))

def ms(x): return f"{x/1000:.2f}s" if x and x>=1000 else (f"{x:.1f}ms" if x else "—")

def agg(vals):
    vals=[v for v in vals if v is not None]
    if not vals: return (None,None)
    return (st.mean(vals), st.pstdev(vals) if len(vals)>1 else 0.0)

metrics = ["ttft_avg","ttft_p50","ttft_p99","itl_avg","itl_p50","req_lat_avg","out_tok_thru","req_thru"]
print(f"{'N':>2} {'arm':>4} | " + " | ".join(f"{m:>12}" for m in metrics))
print("-"*130)
agg_store = {}
for N in (2,4,8):
    for arm in ("off","on"):
        row=[]
        for m in metrics:
            mean,sd = agg(data[(N,arm)][m])
            agg_store[(N,arm,m)] = mean
            if mean is None: row.append("—")
            elif "thru" in m: row.append(f"{mean:.1f}±{sd:.1f}")
            else: row.append(f"{mean:.0f}±{sd:.0f}")
        print(f"{N:>2} {arm:>4} | " + " | ".join(f"{c:>12}" for c in row))

print("\n=== DELTA OFF->ON (negativo = ON migliore per latenza; positivo = ON migliore per throughput) ===")
print(f"{'N':>2} | {'TTFT avg':>10} {'TTFT p50':>10} {'TTFT p99':>10} {'ITL avg':>10} {'out_thru':>10}")
for N in (2,4,8):
    def delta(m, pct=True):
        o,n = agg_store[(N,'off',m)], agg_store[(N,'on',m)]
        if o is None or n is None or o==0: return "—"
        return f"{100*(n-o)/o:+.1f}%"
    print(f"{N:>2} | {delta('ttft_avg'):>10} {delta('ttft_p50'):>10} {delta('ttft_p99'):>10} {delta('itl_avg'):>10} {delta('out_tok_thru'):>10}")
