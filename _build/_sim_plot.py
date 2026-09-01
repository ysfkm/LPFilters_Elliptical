import json, os, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
BASE=r"g:\Shared drives\IAMSYbElectronics\Projects\LPFilters_Elliptical_Mike"
cv=json.load(open(os.path.join(BASE,"_sim_curves.json")))
res=json.load(open(os.path.join(BASE,"_sim_results.json")))
BOARDS=["1kHz","2kHz","5kHz","10kHz","20kHz","50kHz","100kHz","200kHz","500kHz","1MHz"]

fig,axes=plt.subplots(5,2,figsize=(14,20))
axes=axes.flatten()
for idx,b in enumerate(BOARDS):
    ax=axes[idx]
    f=cv["freq"][b]; c=cv["curves"][b]
    ax.semilogx(f,c["ideal"],   color="#888888",ls="--",lw=1.3,label="Ideal (design)")
    ax.semilogx(f,c["actual"],  color="#1f77b4",lw=1.6,label="Actual (current parts)")
    ax.semilogx(f,c["proposed"],color="#d62728",lw=1.6,label="Proposed (Basic swap)")
    ax.set_title(f"LPF {b}",fontweight="bold")
    ax.set_xlabel("Frequency (Hz)"); ax.set_ylabel("|Vout| (dB)")
    ax.grid(True,which="both",alpha=0.3)
    ax.set_ylim(-120,2)
    # mark ideal -3dB and proposed -3dB
    ip=res[b]["ideal"]["f_3dB"]; pp=res[b]["proposed"]["f_3dB"]
    if ip: ax.axvline(ip,color="#888888",ls=":",alpha=0.6)
    if pp: ax.axvline(pp,color="#d62728",ls=":",alpha=0.6)
    ax.legend(fontsize=8,loc="lower left")
fig.suptitle("Elliptic LPF frequency response — Ideal vs Actual vs Proposed-Basic BOM",
             fontsize=15,fontweight="bold",y=0.995)
fig.tight_layout(rect=[0,0,1,0.99])
out=os.path.join(BASE,"LPF Frequency Response (Ideal vs Actual vs Proposed).png")
fig.savefig(out,dpi=110)
print("Saved:",out)
