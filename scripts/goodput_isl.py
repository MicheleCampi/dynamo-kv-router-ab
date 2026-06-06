import json, statistics as st

def analyze(N,arm):
    comp_isl=[]; fail_isl=[]; comp=0; fail=0
    span_ns=0
    for r in (1,2,3):
        starts=[]
        for line in open(f"results/N{N}/{arm}/run_{r}/profile_export.jsonl"):
            line=line.strip()
            if not line: continue
            d=json.loads(line); m=d["metadata"]; met=d["metrics"]
            starts.append(m.get("request_start_ns"))
            err=d.get("error")
            if err or met.get("time_to_first_token",{}).get("value") is None:
                fail+=1
                isl=met.get("error_isl",{}).get("value")
                if isl: fail_isl.append(isl)
            else:
                comp+=1
                isl=met.get("input_sequence_length",{}).get("value")
                if isl: comp_isl.append(isl)
        s=[x for x in starts if x]
        if s: span_ns += (max(s)-min(s))
    span_s = span_ns/1e9
    goodput = comp/span_s if span_s else 0
    return comp,fail,comp_isl,fail_isl,goodput,span_s

print("=== ISL (input length) completate vs fallite, e GOODPUT (completate/sec) — 3 run aggregati ===\n")
for N in (2,4,8):
    for arm in ("off","on"):
        comp,fail,ci,fi,gp,span=analyze(N,arm)
        ci_med = st.median(ci) if ci else 0
        fi_med = st.median(fi) if fi else None
        line=f"N={N} {arm:>3}: completate={comp:>4} fallite={fail:>3} | ISL_compl_med={ci_med:>5.0f}"
        if fi_med is not None:
            line+=f" | ISL_FALLITE_med={fi_med:>5.0f} (min={min(fi)},max={max(fi)})"
        line+=f" | goodput={gp:.2f} req-ok/s"
        print(line)
    print()
