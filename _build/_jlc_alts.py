import json, os, io, sys, time, subprocess, re

BASE = r"g:\Shared drives\IAMSYbElectronics\Projects\LPFilters_Elliptical_Mike"
API = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"
HEADERS = ["-H","Content-Type: application/json","-H","User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
           "-H","Origin: https://jlcpcb.com","-H","Referer: https://jlcpcb.com/parts"]

def call(payload):
    body=json.dumps(payload)
    for _ in range(3):
        try:
            out=subprocess.run(["curl","-s",API,*HEADERS,"--data",body,"--max-time","30"],capture_output=True,timeout=60)
            return (json.loads(out.stdout.decode("utf-8","replace")).get("data") or {}).get("componentPageInfo") or {}
        except Exception:
            time.sleep(1.5)
    return {}

# ---- value parsing ----
CAP_UNITS={"pf":1e-12,"nf":1e-9,"uf":1e-6,"µf":1e-6}
IND_UNITS={"nh":1e-9,"uh":1e-6,"µh":1e-6,"mh":1e-3,"h":1.0}
def parse_cap(s):
    m=re.search(r'([\d.]+)\s*(pf|nf|uf|µf)',str(s).lower())
    return float(m.group(1))*CAP_UNITS[m.group(2)] if m else None
def parse_ind(s):
    m=re.search(r'([\d.]+)\s*(nh|uh|µh|mh|h)\b',str(s).lower())
    return float(m.group(1))*IND_UNITS[m.group(2)] if m else None
def parse_volt(s):
    m=re.findall(r'(\d+(?:\.\d+)?)\s*v\b',str(s).lower())
    return max(float(x) for x in m) if m else None
def parse_diel(s):
    m=re.search(r'\b(c0g|np0|x7r|x5r|x6s|x7s|y5v|x8r)\b',str(s).lower())
    return m.group(1).upper().replace("NP0","C0G") if m else None
def parse_dcr(s):
    """Parse DCR like '5.85Ω' or '88mΩ' / '88m' from an inductor describe string. Returns ohms."""
    if not s: return None
    t=str(s)
    m=re.search(r'([\d.]+)\s*m\s*[ΩΩ]',t)               # milliohm with omega
    if m: return float(m.group(1))/1000.0
    m=re.search(r'([\d.]+)\s*[ΩΩ]',t)                    # ohm with omega
    if m: return float(m.group(1))
    m=re.search(r'([\d.]+)\s*m\b',t)                     # bare 'm' (milliohm)
    if m: return float(m.group(1))/1000.0
    return None

LIBMAP={"base":"Basic","expand":"Extended"}
def lib_of(it):
    if it.get("preferredComponentFlag"): return "Preferred"
    return LIBMAP.get(it.get("componentLibraryType"),it.get("componentLibraryType"))

def find_cap_alts(value_str, footprint, max_results=3):
    """value_str like '330nF'; footprint like '0603'. Returns Basic/Preferred, same footprint, value match, V>=15."""
    target=parse_cap(value_str)
    if target is None: return []
    CAP_FPS=["0201","0402","0603","0805","1206","1210","1812","2220"]
    # search by value across several pages so all footprints surface
    lst=[]
    for pg in (1,2,3):
        info=call({"currentPage":pg,"pageSize":100,"keyword":value_str})
        chunk=info.get("list") or []
        lst+=chunk
        if len(chunk)<100: break
    cands=[]
    for it in lst:
        if lib_of(it) not in ("Basic","Preferred"): continue
        fp=it.get("componentSpecificationEn") or ""
        if fp not in CAP_FPS: continue          # only real MLCC chip footprints
        nm=f"{it.get('erpComponentName','')} {it.get('describe','')}"
        v=parse_cap(it.get("erpComponentName")) or parse_cap(nm)
        if v is None: continue
        rel=abs(v-target)/target if target else 9
        if rel>0.30: continue                   # +/-30% window
        match="exact" if rel<=0.05 else "near"
        volt=parse_volt(nm)
        if volt is not None and volt<15: continue   # >=15V rule
        cands.append({
            "code":it.get("componentCode"),"lib":lib_of(it),
            "footprint":fp,"same_fp":(fp==footprint),
            "value":it.get("erpComponentName"),"diel":parse_diel(nm),
            "volt":volt,"stock":it.get("stockCount"),
            "brand":it.get("componentBrandEn"),"mpn":it.get("componentModelEn"),
            "value_delta_pct":round(rel*100,1),"match":match,
        })
    # priority: same-footprint+exact best; then Basic>Pref; same-fp before diff-fp; exact before near; stock desc
    def tier(c): return {"Basic":0,"Preferred":1}.get(c["lib"],2)
    cands.sort(key=lambda c:(0 if c["same_fp"] else 1,
                             0 if c["match"]=="exact" else 1,
                             tier(c), -(c["stock"] or 0), c["value_delta_pct"]))
    seen=set(); out=[]
    for c in cands:
        if c["code"] in seen: continue
        seen.add(c["code"]); out.append(c)
        if len(out)>=max_results: break
    return out

def find_ind_alts(value_str, footprint, max_dcr=None, max_results=5):
    target=parse_ind(value_str)
    if target is None: return []
    lst=[]
    for pg in (1,2,3):
        info=call({"currentPage":pg,"pageSize":100,"keyword":f"{value_str} inductor"})
        chunk=info.get("list") or []
        lst+=chunk
        if len(chunk)<100: break
    cands=[]
    for it in lst:
        if lib_of(it) not in ("Basic","Preferred"): continue
        v=parse_ind(it.get("erpComponentName")) or parse_ind(it.get("describe"))
        if v is None: continue
        rel=abs(v-target)/target if target else 9
        if rel>0.30: continue
        match="exact" if rel<=0.05 else "near"
        dcr=parse_dcr(it.get("describe"))
        # ESR/DCR rule: only keep parts whose DCR <= original DCR (allow 10% slack); skip if alt DCR unknown
        if max_dcr is not None and dcr is not None and dcr > max_dcr*1.10:
            continue
        fp=it.get("componentSpecificationEn") or ""
        cands.append({"code":it.get("componentCode"),"lib":lib_of(it),
            "footprint":fp,"same_fp":(fp==footprint),"value":it.get("erpComponentName"),
            "stock":it.get("stockCount"),"brand":it.get("componentBrandEn"),
            "mpn":it.get("componentModelEn"),"value_delta_pct":round(rel*100,1),
            "dcr":dcr,"diel":None,"volt":None,"match":match})
    def tier(c): return {"Basic":0,"Preferred":1}.get(c["lib"],2)
    cands.sort(key=lambda c:(0 if c["same_fp"] else 1,0 if c["match"]=="exact" else 1,
                             tier(c),(c["dcr"] if c["dcr"] is not None else 9e9),
                             -(c["stock"] or 0),c["value_delta_pct"]))
    seen=set(); out=[]
    for c in cands:
        if c["code"] in seen: continue
        seen.add(c["code"]); out.append(c)
        if len(out)>=max_results: break
    return out

def _fmt_cap(farads):
    """Render a capacitance in farads back to a JLC-style keyword (e.g. 4.7e-7 -> '470nF')."""
    for unit,scale in (("uF",1e-6),("nF",1e-9),("pF",1e-12)):
        if farads>=scale:
            val=farads/scale
            s=f"{val:.3g}"
            if "." in s: s=s.rstrip("0").rstrip(".")   # only trim zeros after a decimal point
            return f"{s}{unit}"
    return f"{farads:.3g}pF"

# E12 series for generating neighbour values to query
_E12=[1.0,1.2,1.5,1.8,2.2,2.7,3.3,3.9,4.7,5.6,6.8,8.2]
def _e12_neighbours(target, window):
    """E12 values within +/-window of target (farads). Returns set of keyword strings."""
    import math
    out=set()
    for decade in range(-13,1):
        base=10.0**decade
        for m in _E12:
            v=m*base
            if v<=0: continue
            if abs(v-target)/target<=window:
                out.add(_fmt_cap(v))
    return out

def all_cap_candidates(value_str, min_volt=15, window=0.40):
    """Return every Basic/Preferred/Extended MLCC within +/-window of value_str, across chip footprints.
    Queries the value AND its E12 neighbours so wide windows have good recall."""
    target=parse_cap(value_str)
    if target is None: return []
    CAP_FPS=["0201","0402","0603","0805","1206","1210","1812","2220"]
    keywords={value_str} | _e12_neighbours(target, window)
    lst=[]
    for kw in keywords:
        for pg in (1,2,3):
            info=call({"currentPage":pg,"pageSize":100,"keyword":kw})
            chunk=info.get("list") or []
            lst+=chunk
            if len(chunk)<100: break
    out=[]; seen=set()
    for it in lst:
        code=it.get("componentCode")
        if code in seen: continue
        fp=it.get("componentSpecificationEn") or ""
        if fp not in CAP_FPS: continue
        nm=f"{it.get('erpComponentName','')} {it.get('describe','')}"
        v=parse_cap(it.get("erpComponentName")) or parse_cap(nm)
        if v is None: continue
        rel=abs(v-target)/target if target else 9
        if rel>window: continue
        volt=parse_volt(nm)
        if volt is not None and volt<min_volt: continue
        seen.add(code)
        out.append({"code":code,"lib":lib_of(it),"footprint":fp,
            "value":it.get("erpComponentName"),"diel":parse_diel(nm),"volt":volt,
            "stock":it.get("stockCount"),"brand":it.get("componentBrandEn"),
            "mpn":it.get("componentModelEn"),"value_delta_pct":round(rel*100,1),
            "match":"exact" if rel<=0.05 else "near"})
    return out

if __name__=="__main__":
    # quick test
    print("330nF 0603 cap alts:")
    for c in find_cap_alts("330nF","0603"): print(" ",c)
    print("100nF 0603 cap alts:")
    for c in find_cap_alts("100nF","0603"): print(" ",c)
    print("1uF 0805 cap alts:")
    for c in find_cap_alts("1uF","0805"): print(" ",c)
