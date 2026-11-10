import json,sys,statistics as S
rows=[json.loads(l) for l in open(sys.argv[1])]
print(sys.argv[1],"msgs",len(rows))
def q(v,p): v=sorted(v); return v[min(len(v)-1,int(p*len(v)))] if v else None
ages=[r["radio"]["age_ms"] for r in rows if r["radio"].get("age_ms") is not None]
print("age p50/p95",q(ages,.5),q(ages,.95),"catch last",rows[-1]["radio"]["catch_rate"],"trig/rep",rows[-1]["radio"]["triggers"],rows[-1]["radio"]["replies"])
last=rows[-1]["radio"]; print("rssi",last["rssi"],last["rssi_dbm"],"vbat",last["vbat_v"],last["battery"])
hk=set()
for r in rows:
    h=r["radio"]["hub"]
    for k,v in h.items():
        if v not in (None,{},0) and k not in("age_ms","raw","patched"): hk.add(k)
print("hub nonzero fields",sorted(hk), "raw ids",sorted({k for r in rows for k in r["radio"]["hub"]["raw"]}))
prev=None
for r in rows:
    s=(r["radio"]["armed"],r["radio"]["armed_source"],r["fc"].get("armed"),r["fc"]["connected"])
    if s!=prev: print(" t=%.2f radio.armed/src=%s,%s fc.armed=%s fc.conn=%s rc7=%s thr=%s"%((r["t"],)+s[:2]+(s[2],s[3],(r["fc"]["rc"] or [0]*7)[6] if r["fc"]["rc"] else None,(r["fc"]["rc"] or [None])[0])) ); prev=s
