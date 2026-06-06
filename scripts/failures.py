import json

def stats(N,arm,r):
    total=fail=0
    fail_pos=[]
    starts=[]
    for line in open(f"results/N{N}/{arm}/run_{r}/profile_export.jsonl"):
        line=line.strip()
        if not line: continue
        d=json.loads(line); m=d["metadata"]
        total+=1
        starts.append(m.get("request_start_ns"))
        if not m.get("request_ack_ns"):  # 0 o assente = nessun ack = fallita
            fail+=1
            fail_pos.append(m.get("request_start_ns"))
    # posizione mediana dei fallimenti nel run
    pos="—"
    if fail_pos and starts:
        s=sorted(x for x in starts if x); lo,hi=s[0],s[-1]; span=(hi-lo) or 1
        fp=sorted((x-lo)/span*100 for x in fail_pos if x)
        if fp: pos=f"{fp[0]:.0f}-{fp[-1]:.0f}% (med {fp[len(fp)//2]:.0f}%)"
    return total,fail,pos

print(f"{'N':>2} {'arm':>4} {'run':>3} | {'total':>5} {'fail':>4} {'fail%':>6} | {'finestra temporale fallimenti':>30}")
print("-"*75)
for N in (2,4,8):
    for arm in ("off","on"):
        for r in (1,2,3):
            t,f,pos=stats(N,arm,r)
            print(f"{N:>2} {arm:>4} {r:>3} | {t:>5} {f:>4} {100*f/t:>5.1f}% | {pos:>30}")
