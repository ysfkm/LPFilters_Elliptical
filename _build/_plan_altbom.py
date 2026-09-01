import json, os, io, sys, importlib.util
spec=importlib.util.spec_from_file_location("alts", r"g:\Shared drives\IAMSYbElectronics\Projects\LPFilters_Elliptical_Mike\_jlc_alts.py")
alts=importlib.util.module_from_spec(spec); spec.loader.exec_module(alts)
sys.stdout.reconfigure(encoding="utf-8")

BASE=r"g:\Shared drives\IAMSYbElectronics\Projects\LPFilters_Elliptical_Mike"
BOARDS=["1kHz","2kHz","5kHz","10kHz","20kHz","50kHz","100kHz","200kHz","500kHz","1MHz"]
REFS=["L1","L2","C1","C2","C3","C4","C5"]
cand=json.load(open(os.path.join(BASE,"_candidates.json"),encoding="utf-8"))
jcache=json.load(open(os.path.join(BASE,"_jlc_cache.json"),encoding="utf-8"))
def orig_stock(pn): return jcache.get((pn or "").strip(),{}).get("jlc_stock")

# Inject each cell's ORIGINAL part into its candidate pool (so it's always a selectable fallback,
# carrying its real footprint, library type and stock).
for key,rec in cand.items():
    opn=(rec.get("orig_part") or "").strip()
    if not opn: continue
    if any(c["code"]==opn for c in rec["candidates"]): continue
    j=jcache.get(opn,{})
    rec["candidates"].append({"code":opn,"lib":j.get("lib") or "Extended",
        "footprint":rec.get("orig_fp"),"value":rec.get("value"),"diel":None,
        "volt":None,"stock":j.get("jlc_stock"),"brand":j.get("brand"),
        "mpn":j.get("mpn"),"value_delta_pct":0,"match":"orig"})

LIBRANK={"Basic":0,"Preferred":1,"Extended":2}
MIN_STOCK=2000   # "in stock in large numbers" — treat below this as effectively scarce

def is_cap(ref): return ref.startswith("C")

def _stockkey(c):
    s=c.get("stock") or 0
    # bucket: 0 = plenty (>=MIN_STOCK), 1 = some (>0), 2 = none — so plenty always beats scarce
    return 0 if s>=MIN_STOCK else (1 if s>0 else 2)

def pick_best(cands, fp):
    """Selection among candidates at this footprint (any library, +/-40%).
    Goal: a well-stocked Basic at/near the target value, WITHOUT needlessly detuning the filter.
    Order:
      1) stock bucket (plenty >=MIN_STOCK  >  some >0  >  none)   -- guarantees we don't pick dead stock
      2) Basic > Preferred > Extended
      3) closest value to target  (exact wins; only drift when no closer well-stocked Basic exists)
      4) higher stock as the final tiebreak
    Because value-closeness ranks ABOVE raw stock, an exact-value well-stocked Basic always beats a
    farther-value Basic that merely has more stock."""
    pool=[c for c in cands if c["footprint"]==fp]
    if not pool: return None
    pool.sort(key=lambda c:(_stockkey(c), LIBRANK.get(c["lib"],3),
                            c.get("value_delta_pct",99), -(c.get("stock") or 0)))
    return pool[0]

def best_at_fp(cands, fp):  # back-compat alias
    return pick_best(cands, fp)

# For each CAP reference, choose ONE footprint maximizing #boards that get Basic (then Basic+Preferred, then stock).
# Inductors span 8.2uH..10mH -> one common footprint is physically impossible, so they stay per-board (keep orig FP).
plan={}     # ref -> chosen_fp (caps only; None for inductors = per-board original)
per_ref_fp_scores={}
for ref in REFS:
    if not is_cap(ref):
        plan[ref]=None; per_ref_fp_scores[ref]=[]
        continue
    # gather candidate footprints seen across all boards for this ref
    fps=set()
    for b in BOARDS:
        for c in cand[f"{b}|{ref}"]["candidates"]:
            fps.add(c["footprint"])
    # also include original footprints as options
    for b in BOARDS:
        of=cand[f"{b}|{ref}"]["orig_fp"]
        if of: fps.add(of)
    scores=[]
    for fp in fps:
        n_basic_stk=0; n_bp_stk=0; stock=0
        for b in BOARDS:
            cands=cand[f"{b}|{ref}"]["candidates"]
            pick=pick_best(cands,fp)
            if not pick: continue
            stock+=(pick.get("stock") or 0)
            well=(pick.get("stock") or 0)>=MIN_STOCK
            if pick["lib"]=="Basic" and well: n_basic_stk+=1
            if pick["lib"] in ("Basic","Preferred") and well: n_bp_stk+=1
        scores.append((fp,n_basic_stk,n_bp_stk,stock))
    # rank fp: most well-stocked Basic boards, then well-stocked Basic+Pref, then total stock
    scores.sort(key=lambda s:(-s[1],-s[2],-s[3]))
    per_ref_fp_scores[ref]=scores
    plan[ref]=scores[0][0] if scores else None

# Build the alternative BOM assignment per board/ref
altbom={}
for ref in REFS:
    fp_ref=plan[ref]
    for b in BOARDS:
        rec=cand[f"{b}|{ref}"]
        cands=rec["candidates"]
        # caps: use the one chosen ref-wide fp; inductors: use this board's own original fp
        fp = fp_ref if is_cap(ref) else rec["orig_fp"]
        chosen=pick_best(cands,fp) if fp else None
        if chosen is None:
            # nothing at chosen fp for this value -> keep original part on its own fp
            opn=rec["orig_part"]; j=jcache.get((opn or "").strip(),{})
            chosen={"code":opn,"lib":j.get("lib") or "Extended","footprint":rec["orig_fp"],
                    "value":rec["value"],"diel":None,"volt":None,"stock":j.get("jlc_stock"),
                    "brand":j.get("brand"),"mpn":j.get("mpn"),"value_delta_pct":0,"match":"orig"}
            fp=rec["orig_fp"]
        kind=chosen["lib"]
        altbom[f"{b}|{ref}"]={"chosen_fp":fp,"orig_fp":rec["orig_fp"],"value":rec["value"],
                              "orig_part":rec["orig_part"],"pick":chosen,"kind":kind,
                              "is_orig":(chosen["code"]==rec["orig_part"]),
                              "fp_changed":bool(fp and rec["orig_fp"] and fp!=rec["orig_fp"]),
                              "value_changed":bool(chosen.get("value_delta_pct",0) and chosen.get("value_delta_pct",0)>5)}

json.dump({"plan":plan,"scores":per_ref_fp_scores,"altbom":altbom},
          open(os.path.join(BASE,"_altbom.json"),"w",encoding="utf-8"),ensure_ascii=False,indent=1)

# report
print("Chosen footprint per reference & Basic coverage:")
for ref in REFS:
    sc=per_ref_fp_scores[ref][0] if per_ref_fp_scores[ref] else (None,0,0,0)
    print(f"  {ref}: fp={plan[ref]}  -> {sc[1]}/10 boards Basic, {sc[2]}/10 Basic+Preferred")
nb=sum(1 for k,v in altbom.items() if v["pick"]["lib"]=="Basic")
npf=sum(1 for k,v in altbom.items() if v["pick"]["lib"]=="Preferred")
ne=sum(1 for k,v in altbom.items() if v["pick"]["lib"] not in ("Basic","Preferred"))
print(f"\nTotals: {nb} Basic, {npf} Preferred, {ne} Extended/original (of 70 slots)")
