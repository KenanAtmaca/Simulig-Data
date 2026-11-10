"""Refit the national teams in teams.json from real international results.

Source: https://raw.githubusercontent.com/martj42/international_results/master/results.csv
(date, home_team, away_team, home_score, away_score, tournament, city, country, neutral).

Model: the same weighted Poisson model as the clubs, log(mu) = c + h*home + atk_i - def_j,
fitted on every national team in the file (so opponents outside the catalog still inform
the fit). Last 5 years, time decay with a 1.5 year half-life, friendlies count half,
no home advantage on neutral ground, shrinkage toward the mean. Coefficients map to the
engine scale as rating = L + coefficient / 0.035; L is set so the mean overall rating
((attack + defence) / 2) of the catalog's national teams stays what it was before the run.

    python3 national_fit.py <results.csv> <teams.json in> [teams.json out]
"""
import csv, datetime as dt, json, math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SLOPE = 0.035
HALF_LIFE = 1.5 * 365.25
YEARS = 5
FRIENDLY_WEIGHT = 0.5
SHRINK = 4.0
ENGINE_BASE = 1.10
# Non-FIFA competitions (regional/island selections) are left out.
SKIP_TOURNAMENTS = ("CONIFA", "Island Games")

# catalog id -> (catalog name, name in results.csv)
NAMES = {
    "nt-fra": ("Fransa", "France"), "nt-esp": ("İspanya", "Spain"), "nt-eng": ("İngiltere", "England"),
    "nt-arg": ("Arjantin", "Argentina"), "nt-bra": ("Brezilya", "Brazil"), "nt-por": ("Portekiz", "Portugal"),
    "nt-ger": ("Almanya", "Germany"), "nt-ned": ("Hollanda", "Netherlands"), "nt-ita": ("İtalya", "Italy"),
    "nt-bel": ("Belçika", "Belgium"), "nt-nor": ("Norveç", "Norway"), "nt-uru": ("Uruguay", "Uruguay"),
    "nt-tur": ("Türkiye", "Turkey"), "nt-cro": ("Hırvatistan", "Croatia"), "nt-mar": ("Fas", "Morocco"),
    "nt-col": ("Kolombiya", "Colombia"), "nt-den": ("Danimarka", "Denmark"), "nt-jpn": ("Japonya", "Japan"),
    "nt-sui": ("İsviçre", "Switzerland"), "nt-sen": ("Senegal", "Senegal"), "nt-usa": ("ABD", "United States"),
    "nt-mex": ("Meksika", "Mexico"), "nt-kor": ("Güney Kore", "South Korea"), "nt-aus": ("Avustralya", "Australia"),
    "nt-aut": ("Avusturya", "Austria"), "nt-ecu": ("Ekvador", "Ecuador"), "nt-srb": ("Sırbistan", "Serbia"),
    "nt-swe": ("İsveç", "Sweden"), "nt-pol": ("Polonya", "Poland"), "nt-ukr": ("Ukrayna", "Ukraine"),
    "nt-cze": ("Çekya", "Czech Republic"), "nt-sco": ("İskoçya", "Scotland"), "nt-irn": ("İran", "Iran"),
    "nt-par": ("Paraguay", "Paraguay"), "nt-can": ("Kanada", "Canada"), "nt-egy": ("Mısır", "Egypt"),
    "nt-alg": ("Cezayir", "Algeria"), "nt-civ": ("Fildişi Sahili", "Ivory Coast"), "nt-nga": ("Nijerya", "Nigeria"),
    "nt-cmr": ("Kamerun", "Cameroon"), "nt-gha": ("Gana", "Ghana"), "nt-tun": ("Tunus", "Tunisia"),
    "nt-ksa": ("Suudi Arabistan", "Saudi Arabia"), "nt-qat": ("Katar", "Qatar"), "nt-uzb": ("Özbekistan", "Uzbekistan"),
    "nt-jor": ("Ürdün", "Jordan"), "nt-pan": ("Panama", "Panama"), "nt-nzl": ("Yeni Zelanda", "New Zealand"),
    "nt-hun": ("Macaristan", "Hungary"), "nt-gre": ("Yunanistan", "Greece"), "nt-svk": ("Slovakya", "Slovakia"),
    "nt-rou": ("Romanya", "Romania"),
}


# Confederation of each team, read from the competitions it plays in (most frequent tag wins).
# Used for shrinkage: each team is pulled toward its confederation's mean, not the world mean,
# so minnows in weak regions do not inflate the teams that beat them.
CONFED_TAGS = [
    ("UEFA", "UEFA"), ("African Cup of Nations", "CAF"), ("COSAFA", "CAF"), ("CECAFA", "CAF"), ("WAFU", "CAF"),
    ("AFC", "AFC"), ("Gulf Cup", "AFC"), ("AFF", "AFC"), ("ASEAN", "AFC"), ("SAFF", "AFC"), ("EAFF", "AFC"),
    ("CAFA", "AFC"), ("CONCACAF", "CONCACAF"), ("Gold Cup", "CONCACAF"), ("CFU", "CONCACAF"),
    ("Oceania", "OFC"), ("Pacific Games", "OFC"), ("MSG", "OFC"),
]
CONMEBOL = {"Argentina", "Bolivia", "Brazil", "Chile", "Colombia", "Ecuador", "Paraguay", "Peru", "Uruguay", "Venezuela"}


def confederations(path, today):
    since = today - dt.timedelta(days=round(YEARS * 365.25))
    votes = {}
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        if r["date"] < since.isoformat(): continue
        tag = next((c for k, c in CONFED_TAGS if k in r["tournament"]), None)
        if not tag: continue
        for t in (r["home_team"], r["away_team"]):
            v = votes.setdefault(t, {}); v[tag] = v.get(tag, 0) + 1
    out = {t: max(v, key=v.get) for t, v in votes.items()}
    for t in CONMEBOL: out[t] = "CONMEBOL"
    return out


def load(path, today):
    since = today - dt.timedelta(days=round(YEARS * 365.25))
    out, last = [], None
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        if r["home_score"] in ("", "NA") or r["away_score"] in ("", "NA"): continue
        d = dt.date.fromisoformat(r["date"])
        if d < since or d > today: continue
        if any(s in r["tournament"] for s in SKIP_TOURNAMENTS): continue
        w = 0.5 ** ((today - d).days / HALF_LIFE)
        if r["tournament"] == "Friendly": w *= FRIENDLY_WEIGHT
        neutral = r["neutral"].strip().upper() == "TRUE"
        out.append((r["home_team"], r["away_team"], float(r["home_score"]), float(r["away_score"]), w, neutral))
        last = max(last or d, d)
    return out, last


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    src, tin = args[0], args[1]
    tout = args[2] if len(args) > 2 else None
    today = dt.date.fromisoformat(os.environ["SIMULIG_TODAY"]) if os.environ.get("SIMULIG_TODAY") else dt.date.today()
    # Reuse the club model's fit (same code, supports the neutral flag).
    src_bc = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "build_catalog.py"), encoding="utf-8").read()
    ns = {"math": math, "SHRINK": SHRINK}
    exec(src_bc[src_bc.index("def fit("):src_bc.index("def club(")], ns)
    fit = ns["fit"]

    matches, last = load(src, today)
    teams = sorted({m[0] for m in matches} | {m[1] for m in matches})
    print(f"{len(matches)} matches, {len(teams)} national teams, latest {last}")
    cat = json.load(open(tin, encoding="utf-8"))
    nats = [t for t in cat["teams"] if t["kind"] == "national"]
    for t in nats:
        if t["id"] not in NAMES: raise SystemExit(f"no results.csv name for {t['id']} {t['name']}")
        if NAMES[t["id"]][0] != t["name"]: raise SystemExit(f"name mismatch {t['id']}: {t['name']} vs {NAMES[t['id']][0]}")
        if NAMES[t["id"]][1] not in teams: raise SystemExit(f"{NAMES[t['id']][1]} has no matches in the window")
    conf = confederations(src, today)
    atk, dfn, h = fit(matches, teams, {}, shrink=SHRINK, max_iter=5000)
    prior_a, prior_d = {}, {}
    for cf in sorted(set(conf.get(t, "?") for t in teams)):
        grp = [t for t in teams if conf.get(t, "?") == cf]
        if cf == "?": continue  # no confederation competition seen: shrink toward the world mean
        ma = sum(atk[t] for t in grp) / len(grp); md = sum(dfn[t] for t in grp) / len(grp)
        print(f"  {cf:9s} {len(grp):3d} teams, mean attack {ma / SLOPE:+6.1f} defence {md / SLOPE:+6.1f}")
        for t in grp: prior_a[t], prior_d[t] = ma, md
    atk, dfn, h = fit(matches, teams, prior_a, prior_d, shrink=SHRINK, max_iter=5000)
    # Base rate of the fit; the engine's base is 1.10 goals, so split the difference between
    # attack (+) and defence (-) to keep expected goals identical: exp(c) = 1.10 * exp(2 * SLOPE * shift).
    num = sum(w * (hg + ag) for H, A, hg, ag, w, n in matches)
    den = sum(w * (math.exp((0 if n else h) + atk[H] - dfn[A]) + math.exp(atk[A] - dfn[H])) for H, A, hg, ag, w, n in matches)
    c = math.log(num / den)
    shift = (c - math.log(ENGINE_BASE)) / (2 * SLOPE)
    print(f"home advantage x{math.exp(h):.2f}, base rate {math.exp(c):.3f} goals -> attack/defence shift {shift:+.2f}")
    target = sum((t["attack"] + t["defence"]) / 2 for t in nats) / len(nats)
    raw = {t["id"]: (atk[NAMES[t["id"]][1]] / SLOPE + shift, dfn[NAMES[t["id"]][1]] / SLOPE - shift) for t in nats}
    L = target - sum((a + d) / 2 for a, d in raw.values()) / len(raw)
    n_games = {}
    for H, A, *_ in matches:
        n_games[H] = n_games.get(H, 0) + 1; n_games[A] = n_games.get(A, 0) + 1
    before = {t["id"]: (t["attack"], t["defence"]) for t in nats}
    for t in nats:
        a, d = raw[t["id"]]
        t["attack"] = int(round(min(97, max(45, L + a))))
        t["defence"] = int(round(min(97, max(45, L + d))))
    after_mean = sum((t["attack"] + t["defence"]) / 2 for t in nats) / len(nats)
    print(f"level L = {L:.2f}; mean overall {target:.2f} before, {after_mean:.2f} after (rounded)")
    print(f"\n{'':4s}{'team':18s} {'before':>9s} {'after':>9s} {'ovr':>5s} {'d':>5s} {'games':>5s}")
    for i, t in enumerate(sorted(nats, key=lambda t: -(t["attack"] + t["defence"])), 1):
        ba, bd = before[t["id"]]
        delta = (t["attack"] + t["defence"] - ba - bd) / 2
        print(f"{i:3d} {t['name']:18s} {ba:4d}/{bd:<4d} {t['attack']:4d}/{t['defence']:<4d} {(t['attack'] + t['defence']) / 2:5.1f} {delta:+5.1f} {n_games[NAMES[t['id']][1]]:5d}")
    others = sorted(((atk[x] + dfn[x]) / 2 / SLOPE + L, x) for x in teams if x not in {v[1] for v in NAMES.values()})
    print("\nstrongest teams outside the catalog:", ", ".join(f"{x} {v:.0f}" for v, x in others[::-1][:10]))
    if tout:
        json.dump(cat, open(tout, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("wrote", tout)


if __name__ == "__main__":
    main()
