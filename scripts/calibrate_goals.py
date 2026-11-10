"""Per-league goal environment: real goals per game / engine goals per game on the same fixtures.
Writes competitions[].goalFactor into teams.json. 2025-26 counts double (full season, less noise)."""
import csv, json, math, sys
DATA, TEAMS = sys.argv[1], sys.argv[2]
cat = json.load(open(TEAMS)); teams = {t["id"]: t for t in cat["teams"]}
import os
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "build_catalog.py")).read(); ns = {}
exec(src[src.index("M = {"):src.index("# Average club Elo")], {}, ns); M = ns["M"]
def mult(r): return math.exp(0.035 * (min(99, max(40, r)) - 75))
def xg(h, a):
    l = min(4.5, max(0.15, 1.10 * mult(h["attack"]) / mult(a["defence"]) * 1.28))
    m = min(4.5, max(0.15, 1.10 * mult(a["attack"]) / mult(h["defence"])))
    return l + m
factors = {}
for code, (comp, names) in M.items():
    real = model = weight = 0.0
    for season, w in (("2526", 2.0), ("2627", 1.0)):
        for r in csv.DictReader(open(f"{DATA}/{code}_{season}.csv", encoding="utf-8-sig")):
            if not r.get("FTHG"): continue
            h, a = names.get(r["HomeTeam"]), names.get(r["AwayTeam"])
            if not h or not a or h[0] not in teams or a[0] not in teams: continue
            real += w * (int(r["FTHG"]) + int(r["FTAG"])); model += w * xg(teams[h[0]], teams[a[0]]); weight += w
    # Goals scale roughly linearly with the base rate, so the ratio is the base multiplier.
    factors[comp] = round(real / model, 3)
    print(f"{comp:16s} real {real/weight:.2f}  model {model/weight:.2f}  factor {factors[comp]}")
# 1. Lig: same ratio from the Wikipedia results (if lig1_wiki can read them), else the Süper Lig value.
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.dont_write_bytecode = True
    import lig1_wiki
    w = lig1_wiki.load(DATA)
    real = model = weight = 0.0
    for season, wt in (("2025-26", 2.0), ("2026-27", 1.0)):
        for m in w["seasons"][season]:
            if m["forfeit"] or m["home"] not in teams or m["away"] not in teams: continue
            real += wt * (m["hg"] + m["ag"]); model += wt * xg(teams[m["home"]], teams[m["away"]]); weight += wt
    factors["tr-1lig"] = round(real / model, 3)
    print(f"{'tr-1lig':16s} real {real/weight:.2f}  model {model/weight:.2f}  factor {factors['tr-1lig']}")
except Exception as e:
    print(f"tr-1lig: no Wikipedia results ({e}); using the Süper Lig factor")
for c in cat["competitions"]:
    if c["id"] in factors: c["goalFactor"] = factors[c["id"]]
    elif c["id"] == "tr-1lig": c["goalFactor"] = factors["tr-superlig"]
json.dump(cat, open(TEAMS, "w"), ensure_ascii=False, indent=1)
