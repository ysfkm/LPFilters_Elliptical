import json, os, io, sys, time, subprocess
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = r"g:\Shared drives\IAMSYbElectronics\Projects\LPFilters_Elliptical_Mike"
API = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"
HEADERS = [
    "-H","Content-Type: application/json",
    "-H","User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "-H","Origin: https://jlcpcb.com",
    "-H","Referer: https://jlcpcb.com/parts",
]

def call(payload):
    body = json.dumps(payload)
    for attempt in range(3):
        try:
            out = subprocess.run(
                ["curl","-s",API,*HEADERS,"--data",body,"--max-time","30"],
                capture_output=True, timeout=60)
            j = json.loads(out.stdout.decode("utf-8","replace"))
            return ((j.get("data") or {}).get("componentPageInfo") or {})
        except Exception as e:
            time.sleep(1.5)
    return {}

def by_code(code):
    info = call({"currentPage":1,"pageSize":5,"keyword":code})
    lst = info.get("list") or []
    for it in lst:
        if (it.get("componentCode") or "").upper() == code.upper():
            return it
    return lst[0] if lst else None

# ---- 1. annotate every used part ----
parts = sorted(json.load(open(os.path.join(BASE,"_lcsc_cache.json"),encoding="utf-8")).keys())
jcache_path = os.path.join(BASE,"_jlc_cache.json")
jcache = json.load(open(jcache_path,encoding="utf-8")) if os.path.exists(jcache_path) else {}

LIBMAP = {"base":"Basic","expand":"Extended"}
def simplify(it):
    if not it: return {"_missing":True}
    lib = LIBMAP.get(it.get("componentLibraryType"), it.get("componentLibraryType"))
    if it.get("preferredComponentFlag"): lib = "Preferred"
    return {
        "code": it.get("componentCode"),
        "lib": lib,
        "raw_lib": it.get("componentLibraryType"),
        "preferred": bool(it.get("preferredComponentFlag")),
        "jlc_stock": it.get("stockCount"),
        "footprint": it.get("componentSpecificationEn"),
        "value": it.get("erpComponentName"),
        "type": it.get("firstSortName"),
        "category": it.get("secondSortName"),
        "brand": it.get("componentBrandEn"),
        "mpn": it.get("componentModelEn"),
        "desc": it.get("describe"),
        "price1": it.get("initialPrice"),
    }

for i,p in enumerate(parts):
    if p in jcache and not jcache[p].get("_missing"): continue
    jcache[p] = simplify(by_code(p))
    print(f"[{i+1}/{len(parts)}] {p}: {jcache[p].get('lib')} fp={jcache[p].get('footprint')} stk={jcache[p].get('jlc_stock')}")
    json.dump(jcache, open(jcache_path,"w",encoding="utf-8"), ensure_ascii=False, indent=1)
    time.sleep(0.3)

print("ANNOTATION DONE. missing:", [p for p in jcache if jcache[p].get("_missing")])
