import json, statistics as st

def run_data(N,arm,r):
    ttfts=[]; total=0; failed=0
    for line in open(f"results/N{N}/{arm}/run_{r}/profile_export.jsonl"):
        line=line.strip()
        if not line: continue
        d=json.loads(line); m=d["metadata"]; met=d["metrics"]
        total+=1
        t=met.get("time_to_first_token",{}).get("value")
        if t is None or not m.get("request_ack_ns"):
            failed+=1
        else:
            ttfts.append(t)
    return total,failed,ttfts

print("=== N=2: confronto ONESTO OFF vs ON (3 run aggregati) ===\n")
for arm in ("off","on"):
    allt=[]; tot=0; fail=0
    for r in (1,2,3):
        t,f, tt=run_data(2,arm,r)
        tot+=t; fail+=f; allt+=tt
    comp=tot-fail
    print(f"--- {arm.upper()} ---")
    print(f"  richieste totali inviate : {tot}")
    print(f"  completate               : {comp} ({100*comp/tot:.1f}%)")
    print(f"  fallite (no ack)         : {fail} ({100*fail/tot:.1f}%)")
    print(f"  TTFT completate: p50={st.median(allt):.0f}ms  avg={st.mean(allt):.0f}ms  p95={sorted(allt)[int(len(allt)*0.95)]:.0f}ms  max={max(allt):.0f}ms")
    print()

print("=== Lettura ===")
print("OFF: 100% completate ma TTFT degrada (coda). ON: TTFT piu' basso MA ~14% fallite.")
print("Il vantaggio TTFT di ON e' parzialmente "+chr(39)+"survivorship"+chr(39)+": le richieste sotto-pressione")
print("falliscono invece di accodarsi, quindi non gonfiano il TTFT delle completate.")
