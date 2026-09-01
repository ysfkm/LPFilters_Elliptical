import json, os, sys, re
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrow
sys.stdout.reconfigure(encoding="utf-8")

BASE=r"g:\Shared drives\IAMSYbElectronics\Projects\LPFilters_Elliptical_Mike"
OUT=os.path.join(BASE,"Simulation Figures")
os.makedirs(OUT,exist_ok=True)
BOARDS=["1kHz","2kHz","5kHz","10kHz","20kHz","50kHz","100kHz","200kHz","500kHz","1MHz"]
ab=json.load(open(os.path.join(BASE,"_altbom.json"),encoding="utf-8"))["altbom"]
cv=json.load(open(os.path.join(BASE,"_sim_curves.json")))
res=json.load(open(os.path.join(BASE,"_sim_results.json")))

# ---------- extract component values per config from netlists ----------
def netlist(board):
    d=os.path.join(BASE,"LTSpice Files",f"LPFilter_{board}_Elliptical")
    return open(os.path.join(d,f"LPFilter_{board}_Elliptical.net"),encoding="utf-8",errors="replace").read()

def vals_from_net(board):
    nl=netlist(board); v={}
    for ln in nl.splitlines():
        m=re.match(r'(C\d+|L\d+)\s+\S+\s+\S+\s+(\S+)(?:\s+Rser=(\S+))?',ln.strip())
        if m: v[m.group(1)]=(m.group(2), m.group(3))
    return v

def clean_val(s):
    return str(s).replace("µ","u") if s else s

def proposed_vals(board):
    """Proposed config: cap values from altbom; inductors same as actual."""
    out={}
    for i,ref in enumerate(["C1","C2","C3","C4","C5"],1):
        p=ab[f"{board}|{ref}"]["pick"]
        raw=str(p.get("value","")).split("±")[0].strip().replace("µ","u")
        out[ref]=raw
    return out

# ---------- schematic drawing (elliptic LC ladder) ----------
# Topology (per netlist):  Vin -Rser- n1 ; C1 shunt@n1 ; [L1 || C2] series n1->n2 ; C3 shunt@n2 ;
#                          [L2 || C4] series n2->Vout ; C5 shunt@Vout ; RL@Vout
def draw_schematic(path, title, subtitle, caps, inds, ind_rser):
    """caps = dict C1..C5 (strings), inds = dict L1,L2 (strings), ind_rser = dict L1,L2 dcr-or-None"""
    fig,ax=plt.subplots(figsize=(11,4.2))
    ax.set_xlim(0,12); ax.set_ylim(0,6); ax.axis("off")
    yT=4.4; yB=1.2   # top rail, bottom (ground) rail
    def wire(x1,y1,x2,y2,**k): ax.plot([x1,x2],[y1,y2],color="#1a3a6b",lw=1.6,**k)
    def node(x,y): ax.plot(x,y,"s",color="#1a3a6b",ms=4)
    def shunt_cap(x,label):
        wire(x,yT,x,yT-0.7);
        ax.plot([x-0.3,x+0.3],[yT-0.7,yT-0.7],color="#1a3a6b",lw=1.6)
        ax.plot([x-0.3,x+0.3],[yT-0.95,yT-0.95],color="#1a3a6b",lw=1.6)
        wire(x,yT-0.95,x,yB)
        ax.text(x+0.35,yT-0.95,label,fontsize=8,va="center")
    def notch(x0,x1,L,Lr,Cs):
        # parallel L (top) and series-C (bottom of the parallel pair), between x0 and x1 on top rail
        xm=(x0+x1)/2
        # top branch: inductor
        wire(x0,yT,x0,yT+0.6); wire(x0,yT+0.6,xm-0.4,yT+0.6)
        ax.add_patch(plt.Rectangle((xm-0.4,yT+0.45),0.8,0.3,fill=False,ec="#1a3a6b",lw=1.4))
        wire(xm+0.4,yT+0.6,x1,yT+0.6); wire(x1,yT+0.6,x1,yT)
        lbl=L+(f"  Rser={Lr}" if Lr else "")
        ax.text(xm,yT+0.92,lbl,fontsize=8,ha="center")
        # bottom branch (parallel): series cap along the rail
        wire(x0,yT,xm-0.25,yT)
        ax.plot([xm-0.25,xm-0.25],[yT-0.22,yT+0.22],color="#1a3a6b",lw=1.6)
        ax.plot([xm+0.0,xm+0.0],[yT-0.22,yT+0.22],color="#1a3a6b",lw=1.6)
        wire(xm+0.0,yT,x1,yT)
        ax.text(xm-0.12,yT-0.5,Cs,fontsize=8,ha="center")
    # source
    ax.add_patch(plt.Circle((0.7,(yT+yB)/2),0.5,fill=False,ec="#1a3a6b",lw=1.6))
    ax.text(0.7,(yT+yB)/2+0.12,"+",fontsize=11,ha="center"); ax.text(0.7,(yT+yB)/2-0.2,"−",fontsize=11,ha="center")
    ax.text(0.7,yB-0.35,"AC 1\nRser=50",fontsize=7,ha="center",va="top")
    wire(0.7,(yT+yB)/2+0.5,0.7,yT); wire(0.7,yT,1.6,yT)
    wire(0.7,(yT+yB)/2-0.5,0.7,yB)
    # rail nodes
    n1=2.0; n2=6.0; nout=10.0
    node(n1,yT); node(n2,yT); node(nout,yT)
    shunt_cap(n1,caps["C1"])
    notch(n1+0.4,n2-0.4,inds["L1"],ind_rser.get("L1"),caps["C2"]); wire(1.6,yT,n1,yT)
    shunt_cap(n2,caps["C3"])
    notch(n2+0.4,nout-0.4,inds["L2"],ind_rser.get("L2"),caps["C4"])
    shunt_cap(nout,caps["C5"])
    # load
    wire(nout,yT,11.2,yT); wire(11.2,yT,11.2,yT-0.6)
    ax.add_patch(plt.Rectangle((11.05,yT-1.3),0.3,0.7,fill=False,ec="#1a3a6b",lw=1.4))
    wire(11.2,yT-1.3,11.2,yB); ax.text(11.5,yT-0.95,"RL 50",fontsize=8,va="center")
    ax.text(nout+0.15,yT+0.2,"Vout",fontsize=9,color="#1a3a6b")
    # ground rail
    wire(0.7,yB,11.2,yB)
    ax.plot([5.8,6.2],[yB,yB],color="#1a3a6b")  # (rail already drawn)
    ax.text(6,0.35,"GND (0V)",fontsize=7,ha="center",color="#555")
    ax.set_title(title,fontsize=13,fontweight="bold",color="#1a3a6b",loc="left")
    ax.text(0,5.7,subtitle,fontsize=9,color="#444")
    fig.tight_layout()
    fig.savefig(path,dpi=120); plt.close(fig)

# ---------- per-board response plot (3 curves) ----------
def draw_response(path, board):
    f=cv["freq"][board]; c=cv["curves"][board]; rr=res[board]
    fig,ax=plt.subplots(figsize=(11,5.5))
    ax.semilogx(f,c["ideal"],   color="#7a7a7a",ls="--",lw=1.4,label="Ideal (design values)")
    ax.semilogx(f,c["actual"],  color="#1f77b4",lw=1.8,label="Actual (current JLCPCB parts)")
    ax.semilogx(f,c["proposed"],color="#d62728",lw=1.8,label="Proposed (Basic-part swap)")
    for cfg,col in (("ideal","#7a7a7a"),("proposed","#d62728")):
        fcv=rr[cfg]["f_3dB"]
        if fcv: ax.axvline(fcv,color=col,ls=":",alpha=0.5)
    ax.set_title(f"LPF {board} — frequency response",fontsize=13,fontweight="bold")
    ax.set_xlabel("Frequency (Hz)"); ax.set_ylabel("|Vout| (dB)")
    ax.grid(True,which="both",alpha=0.3); ax.set_ylim(-120,2); ax.legend(loc="lower left",fontsize=9)
    # annotate key metrics
    txt=(f"−3dB:  ideal {rr['ideal']['f_3dB']:.0f}  ·  actual {rr['actual']['f_3dB']:.0f}  ·  proposed {rr['proposed']['f_3dB']:.0f} Hz\n"
         f"notch: ideal {rr['ideal']['notch_f']:.0f}@{rr['ideal']['notch_db']}  ·  proposed {rr['proposed']['notch_f']:.0f}@{rr['proposed']['notch_db']} dB")
    ax.text(0.99,0.02,txt,transform=ax.transAxes,fontsize=8,ha="right",va="bottom",
            bbox=dict(boxstyle="round",fc="#f5f5f5",ec="#ccc"))
    fig.tight_layout(); fig.savefig(path,dpi=120); plt.close(fig)

# ---------- run ----------
for b in BOARDS:
    nv=vals_from_net(b)
    # Ideal config: C1..C5, L1,L2 (no Rser in ideal)
    ideal_caps={f"C{i}":clean_val(nv[f"C{i}"][0]) for i in range(1,6)}
    ideal_inds={"L1":clean_val(nv["L1"][0]),"L2":clean_val(nv["L2"][0])}
    ideal_rser={"L1":None,"L2":None}
    # Actual config: C6..C10 map to C1..C5 ; L3,L4 map to L1,L2 (with Rser)
    act_caps={"C1":clean_val(nv["C6"][0]),"C2":clean_val(nv["C7"][0]),"C3":clean_val(nv["C8"][0]),
              "C4":clean_val(nv["C9"][0]),"C5":clean_val(nv["C10"][0])}
    act_inds={"L1":clean_val(nv["L3"][0]),"L2":clean_val(nv["L4"][0])}
    act_rser={"L1":nv["L3"][1],"L2":nv["L4"][1]}
    # Proposed config: proposed caps, inductors same as actual
    pv=proposed_vals(b)
    prop_caps={k:pv[k] for k in ["C1","C2","C3","C4","C5"]}

    draw_schematic(os.path.join(OUT,f"{b}_1_Ideal_schematic.png"),
                   f"LPF {b} — Ideal Circuit","Theoretical design values (no parasitics)",
                   ideal_caps,ideal_inds,ideal_rser)
    draw_schematic(os.path.join(OUT,f"{b}_2_Actual_schematic.png"),
                   f"LPF {b} — Actual Parts (current JLCPCB BOM)","Real part values incl. inductor DCR (Rser)",
                   act_caps,act_inds,act_rser)
    draw_schematic(os.path.join(OUT,f"{b}_3_Proposed_schematic.png"),
                   f"LPF {b} — Proposed Basic-part BOM","Stock-first Basic caps (±40%); inductors unchanged",
                   prop_caps,act_inds,act_rser)
    draw_response(os.path.join(OUT,f"{b}_0_response.png"),b)
    print(f"{b}: 1 response + 3 schematics")

print("FIGURES DONE ->",OUT)
