import json, statistics as st
from collections import defaultdict

def load(N, arm, r):
    return json.load(open(f"results/N{N}/{arm}/inferscope_run{r}.json"))

print(f"{'N':>2} {'arm':>4} | {'#dev_active':>11} | {'util_mean%':>10} | {'util_skew(sd)':>13} | {'pwr_mean_W':>10} | {'pwr_skew_W':>10}")
print("-"*80)
store={}
for N in (2,4,8):
    for arm in ("off","on"):
        # media sui 3 run dello skew e util
        utils_per_run=[]; pwr_per_run=[]; active_per_run=[]
        for r in (1,2,3):
            try: d=load(N,arm,r)
            except FileNotFoundError: continue
            pd=d["gpu"]["per_device"]
            utils=[x["utilization_mean_percent"] for x in pd]
            pwr=[x["power_mean_milliwatts"]/1000.0 for x in pd]
            # "attive" = GPU con util>5% (i worker veri girano su N gpu)
            active=sum(1 for u in utils if u>5)
            utils_per_run.append(utils); pwr_per_run.append(pwr); active_per_run.append(active)
        if not utils_per_run: continue
        # media elemento-per-elemento sui run, poi statistiche tra device
        ndev=len(utils_per_run[0])
        util_mean_dev=[st.mean(run[i] for run in utils_per_run) for i in range(ndev)]
        pwr_mean_dev=[st.mean(run[i] for run in pwr_per_run) for i in range(ndev)]
        # considera solo le GPU attive (le prime N, dove girano i worker)
        active_idx=[i for i in range(ndev) if util_mean_dev[i]>5]
        au=[util_mean_dev[i] for i in active_idx]
        ap=[pwr_mean_dev[i] for i in active_idx]
        util_mean=st.mean(au) if au else 0
        util_skew=st.pstdev(au) if len(au)>1 else 0
        pwr_mean=st.mean(ap) if ap else 0
        pwr_skew=st.pstdev(ap) if len(ap)>1 else 0
        store[(N,arm)]=(util_mean,util_skew,pwr_mean,pwr_skew,len(active_idx))
        print(f"{N:>2} {arm:>4} | {len(active_idx):>11} | {util_mean:>10.1f} | {util_skew:>13.1f} | {pwr_mean:>10.1f} | {pwr_skew:>10.1f}")

print("\n=== SKEW: ON vs OFF (se util_skew ON >> OFF, il KV-router sbilancia il carico) ===")
for N in (2,4,8):
    if (N,'off') in store and (N,'on') in store:
        so=store[(N,'off')][1]; sn=store[(N,'on')][1]
        print(f"N={N}: util_skew OFF={so:.1f}  ON={sn:.1f}  -> ON/OFF ratio={sn/so:.1f}x" if so>0 else f"N={N}: OFF skew~0")
