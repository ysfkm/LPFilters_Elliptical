import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
BASE=r"g:\Shared drives\IAMSYbElectronics\Projects\LPFilters_Elliptical_Mike"
r=json.load(open(os.path.join(BASE,"_sim_results.json")))
BOARDS=["1kHz","2kHz","5kHz","10kHz","20kHz","50kHz","100kHz","200kHz","500kHz","1MHz"]
def pct(new,base):
    if not new or not base: return None
    return round((new-base)/base*100,1)
print(f"{'Board':7} {'fc ideal':>10} {'fc actual':>11} {'fc prop':>10} {'Δfc act':>8} {'Δfc prop':>9}  {'notch prop Δ':>12}")
for b in BOARDS:
    d=r[b]; i=d['ideal']; a=d['actual']; p=d['proposed']
    print(f"{b:7} {i['f_3dB']:>10.0f} {a['f_3dB']:>11.0f} {p['f_3dB']:>10.0f} "
          f"{str(pct(a['f_3dB'],i['f_3dB']))+'%':>8} {str(pct(p['f_3dB'],i['f_3dB']))+'%':>9}  "
          f"{str(pct(p['notch_f'],i['notch_f']))+'%':>12}")
