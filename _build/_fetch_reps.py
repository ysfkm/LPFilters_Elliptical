import json, os, sys, time, subprocess
sys.stdout.reconfigure(encoding="utf-8")
BASE=r"g:\Shared drives\IAMSYbElectronics\Projects\LPFilters_Elliptical_Mike"
API="https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"
HEAD=["-H","Content-Type: application/json","-H","User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
      "-H","Origin: https://jlcpcb.com","-H","Referer: https://jlcpcb.com/parts"]
def call(pl):
    for _ in range(3):
        try:
            out=subprocess.run(["curl","-s",API,*HEAD,"--data",json.dumps(pl),"--max-time","30"],capture_output=True,timeout=60)
            return (json.loads(out.stdout.decode("utf-8","replace")).get("data") or {}).get("componentPageInfo") or {}
        except Exception: time.sleep(1.5)
    return {}
LIBMAP={"base":"Basic","expand":"Extended"}
def simplify(it):
    lib=LIBMAP.get(it.get("componentLibraryType"),it.get("componentLibraryType"))
    if it.get("preferredComponentFlag"): lib="Preferred"
    return {"code":it.get("componentCode"),"lib":lib,"jlc_stock":it.get("stockCount"),
            "footprint":it.get("componentSpecificationEn"),"value":it.get("erpComponentName"),
            "type":it.get("firstSortName"),"category":it.get("secondSortName"),
            "brand":it.get("componentBrandEn"),"mpn":it.get("componentModelEn"),"desc":it.get("describe")}

jc=json.load(open(os.path.join(BASE,"_jlc_cache.json"),encoding="utf-8"))
ab=json.load(open(os.path.join(BASE,"_altbom.json"),encoding="utf-8"))["altbom"]
reps=set(v["pick"]["code"] for v in ab.values() if v["pick"].get("code"))
missing=[c for c in reps if c not in jc]
print("fetching",len(missing),"replacement parts")
for i,c in enumerate(missing):
    info=call({"currentPage":1,"pageSize":5,"keyword":c})
    lst=info.get("list") or []
    hit=next((x for x in lst if (x.get("componentCode") or "").upper()==c.upper()), lst[0] if lst else None)
    if hit:
        jc[c]=simplify(hit); print(f"  [{i+1}] {c}: {jc[c]['type']} stk={jc[c]['jlc_stock']}")
    else:
        jc[c]={"code":c,"_error":"not found"}; print(f"  [{i+1}] {c}: NOT FOUND")
    time.sleep(0.3)
json.dump(jc,open(os.path.join(BASE,"_jlc_cache.json"),"w",encoding="utf-8"),ensure_ascii=False,indent=1)
print("DONE")
