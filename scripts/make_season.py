"""Real 2026-27 Süper Lig snapshot from football-data.co.uk results (T1_2627.csv).

    python3 make_season.py <T1_2627.csv> <season-tr-superlig.json>

updatedAt is the generation time (UTC); the remaining fixtures are packed into the
matchweeks still to play (random but reproducible, seed 2026).
"""
import csv, datetime as dt, json, os, random, sys
from collections import defaultdict
# Team ids come from the football-data name table in build_catalog.py (single source of truth).
_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "build_catalog.py"), encoding="utf-8").read()
_ns = {}
exec(_src[_src.index("M = {"):_src.index("# Average club Elo")], {}, _ns)
ID = {fd: v[0] for fd, v in _ns["M"]["T1"][1].items()}
rows = [r for r in csv.DictReader(open(sys.argv[1], encoding="utf-8-sig")) if r.get("HomeTeam") and r.get("FTHG")]
rows.sort(key=lambda r: dt.datetime.strptime(r["Date"], "%d/%m/%Y"))
count = defaultdict(int)
table = {}
played, done = [], set()
for r in rows:
    h, a = ID[r["HomeTeam"]], ID[r["AwayTeam"]]
    count[h] += 1; count[a] += 1
    rnd = max(count[h], count[a])
    hg, ag = int(r["FTHG"]), int(r["FTAG"])
    played.append(dict(fixture=dict(home=h, away=a, round=rnd), score=dict(home=hg, away=ag)))
    done.add((h, a))
    for t, f, g in ((h, hg, ag), (a, ag, hg)):
        x = table.setdefault(t, dict(teamID=t, played=0, won=0, drawn=0, lost=0, goalsFor=0, goalsAgainst=0)); x["played"] += 1; x["goalsFor"] += f; x["goalsAgainst"] += g
        x["won" if f > g else "drawn" if f == g else "lost"] += 1
week = max(p["fixture"]["round"] for p in played)
teams = [i for i in dict.fromkeys(ID.values()) if i in table]  # catalog order
if len(teams) != 18: raise SystemExit(f"expected 18 Süper Lig teams in the results, found {len(teams)}")
table = {i: table[i] for i in teams}
left = [(h, a) for h in teams for a in teams if h != a and (h, a) not in done]
# Pack the remaining games into exactly 34 - week matchweeks: each week is a perfect matching
# of the remaining-games graph, found by randomized backtracking, restarting on dead ends.
rng = random.Random(2026)
need = 34 - week

def perfect_matching(pool):
    """pool: list of (home, away). Returns 9 games covering all 18 teams once, or None."""
    by_team = defaultdict(list)
    for m in pool: by_team[m[0]].append(m); by_team[m[1]].append(m)
    chosen, used = [], set()
    def go():
        free = [t for t in teams if t not in used]
        if not free: return True
        t = min(free, key=lambda x: sum(1 for m in by_team[x] if m[0] not in used and m[1] not in used))
        opts = [m for m in by_team[t] if m[0] not in used and m[1] not in used]
        rng.shuffle(opts)
        for m in opts:
            chosen.append(m); used.update(m)
            if go(): return True
            chosen.pop(); used.difference_update(m)
        return False
    return chosen[:] if go() else None

for attempt in range(500):
    pool = left[:]; weeks = []
    while len(weeks) < need:
        wk = perfect_matching(pool)
        if wk is None: break
        for m in wk: pool.remove(m)
        weeks.append(wk)
    if len(weeks) == need and not pool: break
else:
    raise SystemExit("could not pack fixtures")
remaining = [dict(home=h, away=a, round=week + 1 + i) for i, wk in enumerate(weeks) for h, a in wk]
now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
snap = dict(isSample=False, updatedAt=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            state=dict(competitionID="tr-superlig", week=week, table=list(table.values()), playedResults=played, remainingFixtures=remaining))
json.dump(snap, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
print("attempt", attempt, "week", week, len(played), "played", len(remaining), "remaining")
for t in sorted(table.values(), key=lambda x: (-(3 * x["won"] + x["drawn"]), -(x["goalsFor"] - x["goalsAgainst"]))):
    print(f'{t["teamID"]:8s} {t["played"]:2d} {3*t["won"]+t["drawn"]:3d}  {t["goalsFor"]}-{t["goalsAgainst"]}')
