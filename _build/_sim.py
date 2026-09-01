import json, os, sys, re, subprocess, math
sys.stdout.reconfigure(encoding="utf-8")

BASE=r"g:\Shared drives\IAMSYbElectronics\Projects\LPFilters_Elliptical_Mike"
LT=r"C:\Users\USER\AppData\Local\Programs\ADI\LTspice\LTspice.exe"
SIMDIR=os.path.join(BASE,"_sim")
os.makedirs(SIMDIR, exist_ok=True)
BOARDS=["1kHz","2kHz","5kHz","10kHz","20kHz","50kHz","100kHz","200kHz","500kHz","1MHz"]
ab=json.load(open(os.path.join(BASE,"_altbom.json"),encoding="utf-8"))["altbom"]

def lt(args):
    p=subprocess.run([LT,*args],capture_output=True,timeout=120)
    return p.returncode

# value parser -> SPICE float
UNIT={"f":1e-15,"p":1e-12,"n":1e-9,"u":1e-6,"µ":1e-6,"m":1e-3,"k":1e3,"meg":1e6}
def to_f(s):
    s=str(s).strip().replace("µ","u")
    m=re.match(r'([\d.]+)\s*(meg|[fpnumk])?',s,re.I)
    if not m: return None
    val=float(m.group(1)); u=(m.group(2) or "").lower()
    return val*UNIT.get(u,1.0)

def proposed_cap(board, ref):
    """proposed cap value in farads for this board/ref"""
    v=ab[f"{board}|{ref}"]["pick"].get("value")
    return to_f(v)

# ---- per board: make netlist, build combined 3-circuit netlist, run, parse ----
def gen_netlist(board):
    d=os.path.join(BASE,"LTSpice Files",f"LPFilter_{board}_Elliptical")
    asc=os.path.join(d,f"LPFilter_{board}_Elliptical.asc")
    lt(["-netlist",asc])
    net=os.path.join(d,f"LPFilter_{board}_Elliptical.net")
    return open(net,encoding="utf-8",errors="replace").read()

def parse_actual_lines(netlist):
    """grab the 'Actual Parts' branch lines (Vin1..RL1) and the .ac directive."""
    acline=None
    for ln in netlist.splitlines():
        s=ln.strip()
        if s.lower().startswith(".ac"): acline=s
    return acline

def build_combined(board, netlist):
    """Return combined netlist string with ideal(Vout1), actual(Vout2), proposed(Vout3)."""
    acline=parse_actual_lines(netlist)
    lines=["* combined sim for "+board]
    # keep ideal + actual branches verbatim from generated netlist (component lines only)
    for ln in netlist.splitlines():
        s=ln.strip()
        if not s or s.startswith("*"): continue
        if s.lower().startswith(".ac") or s.startswith(".backanno") or s.startswith(".end"): continue
        lines.append(s)
    # proposed branch: clone actual topology with proposed cap values, new nodes P*, source Vin2->Vout3
    # actual mapping: C6=C1(shunt), C7=C2(series L3), L3=L1, C8=C3(shunt), C9=C4(series L4), L4=L2, C10=C5(shunt)
    # find actual inductor values+Rser from netlist
    ind={}
    for ln in netlist.splitlines():
        s=ln.strip()
        m=re.match(r'(L3|L4)\s+(\S+)\s+(\S+)\s+(\S+)(?:\s+Rser=(\S+))?',s)
        if m: ind[m.group(1)]=(m.group(4), m.group(5) or "0")
    c1=proposed_cap(board,"C1"); c2=proposed_cap(board,"C2"); c3=proposed_cap(board,"C3")
    c4=proposed_cap(board,"C4"); c5=proposed_cap(board,"C5")
    l3v,l3r=ind.get("L3",("0",0)); l4v,l4r=ind.get("L4",("0",0))
    P=[
      f"Vin2 P001 0 AC 1 Rser=50",
      f"Cp1 P001 0 {c1:.6g}",
      f"Cp2 P002 P001 {c2:.6g}",
      f"Lp1 P002 P001 {l3v} Rser={l3r}",
      f"Cp3 P002 0 {c3:.6g}",
      f"Cp4 Vout3 P002 {c4:.6g}",
      f"Lp2 Vout3 P002 {l4v} Rser={l4r}",
      f"Cp5 Vout3 0 {c5:.6g}",
      f"RLp Vout3 0 50",
    ]
    lines+=P
    lines.append(acline)
    lines.append(".end")
    return "\n".join(lines)

def _cval(s):
    """parse a complex token: 're,im' (comma) or 're\\tim' already split -> handled by caller."""
    a=s.split(",")
    return float(a[0]), float(a[1])

def parse_raw(path):
    """parse ASCII raw -> (freqs, series{var->[(re,im)]}, vnames). LTspice AC ascii format:
    per point: '<idx>\\t<re>,<im>' for the first var (frequency), then '\\t<re>,<im>' per remaining var."""
    txt=open(path,encoding="latin-1").read()
    hdr,_,data=txt.partition("Values:")
    vnames=[]; invars=False
    for ln in hdr.splitlines():
        if ln.strip().startswith("Variables:"): invars=True; continue
        if invars:
            m=re.match(r'\s*\d+\s+(\S+)\s+\S+',ln)
            if m: vnames.append(m.group(1))
    npts=int(re.search(r'No\. Points:\s*(\d+)',hdr).group(1))
    nv=len(vnames)
    # tokenize: each data line has one complex value (possibly preceded by point index)
    rows=[l for l in data.splitlines() if l.strip()!=""]
    freqs=[]; series={v:[] for v in vnames}
    assert len(rows)==npts*nv, f"raw parse: {len(rows)} rows != {npts}*{nv}"
    for pt in range(npts):
        for k in range(nv):
            tok=rows[pt*nv+k].split()      # first var line is 'idx\tre,im' -> ['idx','re,im']; others '\tre,im' -> ['re,im']
            cstr=tok[-1]
            r,im=_cval(cstr)
            series[vnames[k]].append((r,im))
            if k==0: freqs.append(r)        # frequency real part
    return freqs, series, vnames

def db(c):
    r,im=c; mag=math.hypot(r,im)
    return 20*math.log10(mag) if mag>0 else -300

def analyze(freqs, series):
    out={}
    for name,key in (("ideal","v(vout1)"),("actual","v(vout2)"),("proposed","v(vout3)")):
        kk=next((v for v in series if v.lower()==key),None)
        if not kk: out[name]=None; continue
        mags=[db(series[kk][i]) for i in range(len(freqs))]
        # passband ref = max gain (low freq)
        ref=max(mags)
        # -3dB cutoff: first freq where mag drops 3dB below ref scanning up
        fc=None
        for i in range(len(freqs)):
            if mags[i]<=ref-3:
                fc=freqs[i]; break
        # notch: min magnitude and its freq
        mn=min(range(len(mags)),key=lambda i:mags[i])
        out[name]={"passband_db":round(ref,2),"f_3dB":fc,"notch_f":freqs[mn],"notch_db":round(mags[mn],1),
                   "mags":mags}
    return out

results={}
freq_axis={}
for b in BOARDS:
    nl=gen_netlist(b)
    combined=build_combined(b,nl)
    cf=os.path.join(SIMDIR,f"{b}.cir")
    open(cf,"w",encoding="utf-8").write(combined)
    rc=lt(["-b","-ascii",cf])
    raw=os.path.join(SIMDIR,f"{b}.raw")
    if not os.path.exists(raw):
        print(f"{b}: NO RAW (rc={rc})"); continue
    freqs,series,vn=parse_raw(raw)
    a=analyze(freqs,series)
    results[b]=a; freq_axis[b]=freqs
    def fmt(x): return f"{x/1000:.3f}k" if x and x>=1000 else (f"{x:.1f}" if x else "—")
    print(f"{b:7} | ideal fc={fmt(a['ideal']['f_3dB'])} notch={fmt(a['ideal']['notch_f'])}@{a['ideal']['notch_db']}dB"
          f" | actual fc={fmt(a['actual']['f_3dB'])} notch={fmt(a['actual']['notch_f'])}@{a['actual']['notch_db']}dB"
          f" | proposed fc={fmt(a['proposed']['f_3dB'])} notch={fmt(a['proposed']['notch_f'])}@{a['proposed']['notch_db']}dB")

json.dump({b:{k:(v and {kk:vv for kk,vv in v.items() if kk!='mags'}) for k,v in results[b].items()} for b in results},
          open(os.path.join(BASE,"_sim_results.json"),"w"),indent=1)
# also dump full curves for plotting
json.dump({"freq":freq_axis,"curves":{b:{k:(results[b][k]['mags'] if results[b][k] else None) for k in results[b]} for b in results}},
          open(os.path.join(BASE,"_sim_curves.json"),"w"))
print("SIM DONE")
