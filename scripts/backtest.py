import csv, json, math, sys

DATA = sys.argv[1]; _cat = json.load(open(sys.argv[2])); teams = {t["id"]: t for t in _cat["teams"]}; GF = {c["id"]: c.get("goalFactor", 1) or 1 for c in _cat["competitions"]}
import os
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "build_catalog.py")).read()
M = {}
exec(src[src.index("M = {"):src.index("# Average club Elo")], {}, M) ; M = M["M"]
BASE, HOME, SLOPE, PIVOT, RHO = 1.10, 1.28, 0.035, 75.0, -0.10
def mult(r): return math.exp(SLOPE * (min(99, max(40, r)) - PIVOT))
def probs(h, a, f=1):
    l = min(4.5, max(0.15, BASE * f * mult(h["attack"]) / mult(a["defence"]) * HOME))
    m = min(4.5, max(0.15, BASE * f * mult(a["attack"]) / mult(h["defence"])))
    pmf = lambda lam: [math.exp(-lam) * lam ** k / math.factorial(k) for k in range(13)]
    ph, pa = pmf(l), pmf(m)
    def tau(x, y):
        return {(0, 0): 1 - l * m * RHO, (0, 1): 1 + l * RHO, (1, 0): 1 + m * RHO, (1, 1): 1 - RHO}.get((x, y), 1)
    H = D = A = 0
    for x in range(13):
        for y in range(13):
            p = ph[x] * pa[y] * tau(x, y)
            if x > y: H += p
            elif x == y: D += p
            else: A += p
    s = H + D + A
    return H / s, D / s, A / s, l, m
print(f"{'lig':4s} {'maç':>4s} {'|ΔEv|':>6s} {'|ΔBer|':>6s} {'Brier model':>11s} {'Brier piyasa':>12s} {'gol model':>9s} {'gol gerçek':>10s} {'ev% m/g':>9s}")
for code, (comp, names) in M.items():
    rows = [r for r in csv.DictReader(open(f"{DATA}/{code}_2627.csv", encoding="utf-8-sig")) if r.get("FTHG")]
    n = 0; dH = dD = 0; bm = bk = 0; gm = ga = 0; hw_m = hw_a = 0
    for r in rows:
        h, a = names.get(r["HomeTeam"]), names.get(r["AwayTeam"])
        if not h or not a: continue
        th, ta = teams.get(h[0]), teams.get(a[0])
        if not th or not ta: continue
        pH, pD, pA, l, m = probs(th, ta, GF[comp])
        try:
            oh, od, oa = float(r["AvgH"]), float(r["AvgD"]), float(r["AvgA"])
        except (KeyError, ValueError):
            continue
        inv = 1 / oh + 1 / od + 1 / oa
        qH, qD, qA = 1 / oh / inv, 1 / od / inv, 1 / oa / inv
        hg, ag = int(r["FTHG"]), int(r["FTAG"])
        res = (1, 0, 0) if hg > ag else (0, 1, 0) if hg == ag else (0, 0, 1)
        n += 1; dH += abs(pH - qH); dD += abs(pD - qD)
        bm += sum((p - o) ** 2 for p, o in zip((pH, pD, pA), res))
        bk += sum((p - o) ** 2 for p, o in zip((qH, qD, qA), res))
        gm += l + m; ga += hg + ag; hw_m += pH; hw_a += res[0]
    print(f"{code:4s} {n:4d} {dH/n:6.3f} {dD/n:6.3f} {bm/n:11.3f} {bk/n:12.3f} {gm/n:9.2f} {ga/n:10.2f} {hw_m/n*100:4.0f}/{hw_a/n*100:3.0f}")
