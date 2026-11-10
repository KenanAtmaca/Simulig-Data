"""One-command weekly update of the Simülig data files.

Downloads every source, runs the club fit (build_catalog.py, Süper Lig + 1. Lig joint fit),
the national-team fit (national_fit.py), the Süper Lig snapshot (make_season.py) and the
goal calibration (calibrate_goals.py) and the club squads from Wikipedia (squads_wiki.py),
validates the result and only then writes

    <out>/teams.json, <out>/season-tr-superlig.json, <out>/squads.json, <out>/manifest.json

Nothing is written (exit code 1) if a download, a step or a validation fails.
If the data did not change (apart from the snapshot timestamp) nothing is written either.

    python3 update_all.py --out <folder>            # e.g. the data repository root
    python3 update_all.py --out out --app            # also copy the two JSON files into Simulig/Data
    python3 update_all.py --work w --offline         # reuse files already downloaded into w
    python3 update_all.py --squads-only --app        # only refresh squads.json (+ manifest hash)

If the squads step fails (a Wikipedia page changed beyond what the parser handles) the previous
<out>/squads.json is kept and the rest of the update goes ahead; --strict-squads makes it fatal.

The previous teams.json is the base for everything that is not refitted (legends, competition
names, colours) and for the national-team scale: --base, else <out>/teams.json, else the app copy.
"""
import argparse, datetime as dt, hashlib, json, os, shutil, subprocess, sys, tempfile, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True
APP_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "Simulig", "Data"))
SEASON = "2026-27"
FD_SEASONS = ["2526", "2627"]
FD_LEAGUES = ["E0", "SP1", "I1", "D1", "F1", "N1", "P1", "T1"]
FD_URL = "https://www.football-data.co.uk/mmz4281/{season}/{code}.csv"
INTL_URL = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
UA = "SimuligDataPipeline/1.0 (weekly data update script)"
FILES = ["teams.json", "season-tr-superlig.json", "squads.json"]
EXPECTED = {"tr-superlig": 18, "tr-1lig": 20, "eng-premier": 20, "esp-laliga": 20, "ita-seriea": 20,
            "ger-bundesliga": 18, "fra-ligue1": 18, "ned-eredivisie": 18, "por-liga": 18,
            "national": 52, "legends": 50}


class Fail(Exception):
    pass


def log(*a):
    print(*a, flush=True)


def download(url, path, check):
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as r:
                data = r.read()
            text = data.decode("utf-8-sig")
            if not check(text): raise Fail(f"unexpected content from {url}")
            open(path, "wb").write(data)
            return
        except Exception as e:  # network hiccup: retry
            last = e
            time.sleep(3 * (attempt + 1))
    raise Fail(f"download failed: {url}: {last}")


def fetch_all(work):
    for s in FD_SEASONS:
        for code in FD_LEAGUES:
            path = os.path.join(work, f"{code}_{s}.csv")
            download(FD_URL.format(season=s, code=code), path, lambda t: t.startswith("Div,") and "HomeTeam" in t.split("\n")[0])
            n = sum(1 for line in open(path, encoding="utf-8-sig") if line.strip()) - 1
            log(f"  {code}_{s}.csv  {n} matches")
    download(INTL_URL, os.path.join(work, "results.csv"), lambda t: t.startswith("date,home_team,away_team"))
    log("  results.csv (international)")
    import lig1_wiki
    try:
        lig1_wiki.fetch(work)
        log("  1. Lig pages from tr.wikipedia.org")
    except Exception as e:  # build_catalog falls back to its table; reported below
        log(f"  WARNING: Wikipedia fetch failed: {e}")


def run(step, args, logf):
    cmd = [sys.executable, os.path.join(HERE, step)] + args
    log(f"\n== {step} {' '.join(os.path.basename(a) for a in args)}")
    p = subprocess.run(cmd, capture_output=True, text=True)
    logf.write(f"\n== {' '.join(cmd)}\n{p.stdout}{p.stderr}")
    if p.returncode != 0:
        log(p.stdout[-3000:], p.stderr[-3000:])
        raise Fail(f"{step} failed with exit code {p.returncode}")
    return p.stdout


def validate(teams, season, base):
    errs = []
    ids = [t["id"] for t in teams["teams"]]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup: errs.append(f"duplicate ids: {dup}")
    comps = {c["id"]: c for c in teams["competitions"]}
    count = {}
    for t in teams["teams"]:
        count[t["competition"]] = count.get(t["competition"], 0) + 1
        for k in ("id", "name", "short", "country", "competition", "kind", "attack", "defence", "colors"):
            if k not in t: errs.append(f"{t.get('id')}: missing {k}")
        for k in ("attack", "defence"):
            v = t.get(k)
            if not isinstance(v, int) or not 45 <= v <= 97: errs.append(f"{t['id']}: {k} {v} outside 45..97")
        if t["competition"] not in comps: errs.append(f"{t['id']}: unknown competition {t['competition']}")
        if len(t.get("colors", [])) != 2: errs.append(f"{t['id']}: needs two colours")
    for cid, n in EXPECTED.items():
        if count.get(cid, 0) != n: errs.append(f"{cid}: {count.get(cid, 0)} teams, expected {n}")
        if "teams" in comps.get(cid, {}) and comps[cid]["teams"] != count.get(cid, 0):
            errs.append(f"{cid}: competition says {comps[cid]['teams']} teams, catalog has {count.get(cid, 0)}")
    for cid, c in comps.items():
        if c.get("format") == "league" and not 0.7 <= (c.get("goalFactor") or 0) <= 1.6:
            errs.append(f"{cid}: goalFactor {c.get('goalFactor')} implausible")
    nat = [t for t in teams["teams"] if t["kind"] == "national"]
    bnat = [t for t in base["teams"] if t["kind"] == "national"]
    if nat and bnat:
        m1 = sum(t["attack"] + t["defence"] for t in nat) / 2 / len(nat)
        m0 = sum(t["attack"] + t["defence"] for t in bnat) / 2 / len(bnat)
        if abs(m1 - m0) > 0.5: errs.append(f"national mean overall moved {m0:.2f} -> {m1:.2f}")
    legends = lambda c: sorted((t["id"], t["attack"], t["defence"]) for t in c["teams"] if t["kind"] == "legend")
    if legends(teams) != legends(base): errs.append("legend teams changed")

    # season snapshot
    st = season.get("state", {})
    if season.get("isSample") is not False: errs.append("isSample must be false")
    try:
        dt.datetime.strptime(season.get("updatedAt", ""), "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        errs.append(f"updatedAt not ISO8601 UTC: {season.get('updatedAt')}")
    if st.get("competitionID") != "tr-superlig": errs.append("snapshot competitionID")
    sl = {t["id"] for t in teams["teams"] if t["competition"] == "tr-superlig"}
    known = {t["id"] for t in teams["teams"]}
    played, remaining, table = st.get("playedResults", []), st.get("remainingFixtures", []), st.get("table", [])
    in_snap = {p["fixture"]["home"] for p in played} | {p["fixture"]["away"] for p in played} | {r["teamID"] for r in table}
    missing = sorted(in_snap - known)
    if missing: errs.append(f"snapshot teams missing from teams.json: {missing}")
    if in_snap != sl: errs.append(f"snapshot teams differ from Süper Lig teams: {sorted(in_snap ^ sl)}")
    pairs = [(p["fixture"]["home"], p["fixture"]["away"]) for p in played] + [(r["home"], r["away"]) for r in remaining]
    want = {(h, a) for h in sl for a in sl if h != a}
    if len(pairs) != len(set(pairs)) or set(pairs) != want:
        errs.append(f"played + remaining fixtures do not cover every pair exactly once ({len(pairs)} games, {len(set(pairs) & want)}/{len(want)} pairs)")
    week = st.get("week")
    if not isinstance(week, int) or not 1 <= week <= 34: errs.append(f"week {week} outside 1..34")
    else:
        if max((p["fixture"]["round"] for p in played), default=0) != week: errs.append("week is not the last played round")
        rounds = {}
        for r in remaining:
            rounds.setdefault(r["round"], []).append(r)
        if sorted(rounds) != list(range(week + 1, 35)): errs.append(f"remaining rounds {sorted(rounds)[:3]}... do not run {week + 1}..34")
        for rnd, games in rounds.items():
            ts = [g["home"] for g in games] + [g["away"] for g in games]
            if len(games) != 9 or len(set(ts)) != 18: errs.append(f"round {rnd}: not 9 games with every team once")
        pl = [r["played"] for r in table]
        if pl and (max(pl) > week or min(pl) < week - 3): errs.append(f"games played {min(pl)}..{max(pl)} do not fit week {week}")
        if len(played) != sum(pl) // 2: errs.append("table does not match played results")
        # 2026-27 started 14 Aug 2026; a matchweek cannot be ahead of the calendar
        weeks_elapsed = (dt.date.today() - dt.date(2026, 8, 14)).days / 7 + 1
        if week > weeks_elapsed + 1: errs.append(f"week {week} ahead of the calendar ({weeks_elapsed:.0f} weeks since kick-off)")
    return errs


def squads_step(work, teams_path, stage, out, a, logf):
    """Build <stage>/squads.json; on failure reuse <out>/squads.json unless --strict-squads."""
    Q = os.path.join(stage, "squads.json")
    args = [os.path.join(work, "wiki-squads"), teams_path, Q] + (["--offline"] if a.offline else [])
    try:
        o = run("squads_wiki.py", args, logf)
        log("\n".join(l for l in o.splitlines() if l.startswith(("squads:", "  ", "wrote")) and "INVALID" not in l))
    except Fail as e:
        prev = os.path.join(out, "squads.json")
        if a.strict_squads or not os.path.exists(prev): raise
        log(f"  WARNING: {e}; keeping the previous squads.json")
        shutil.copy(prev, Q)


def validate_squads(path, teams):
    import squads_wiki
    clubs = [t["id"] for t in teams["teams"] if t["kind"] == "club"]
    return ["squads: " + e for e in squads_wiki.validate(json.load(open(path, encoding="utf-8")), clubs)]


def write_out(stage, out, version):
    """Stamp the data version into teams.json and squads.json in the stage folder."""
    for n in ("teams.json", "squads.json"):
        p = os.path.join(stage, n)
        d = json.load(open(p, encoding="utf-8")); d["version"] = version
        json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join(HERE, "output"), help="folder for teams.json, season-tr-superlig.json, manifest.json")
    ap.add_argument("--work", help="working folder for downloads and logs (default: a temporary folder)")
    ap.add_argument("--base", help="previous teams.json (default: <out>/teams.json, else the app copy)")
    ap.add_argument("--app", action="store_true", help=f"also write teams.json, season-tr-superlig.json and squads.json into {APP_DIR}")
    ap.add_argument("--app-dir", default=APP_DIR, help="app bundle data folder used with --app")
    ap.add_argument("--offline", action="store_true", help="do not download; use the files already in --work")
    ap.add_argument("--strict-wiki", action="store_true", help="fail instead of using the fallback 1. Lig table")
    ap.add_argument("--strict-squads", action="store_true", help="fail instead of keeping the previous squads.json")
    ap.add_argument("--squads-only", action="store_true",
                    help="only rebuild squads.json and its manifest entry; teams.json, the season file and the version stay as they are")
    ap.add_argument("--force", action="store_true", help="write even if nothing changed")
    a = ap.parse_args()

    out = os.path.abspath(a.out)
    base = a.base or next((p for p in (os.path.join(out, "teams.json"), os.path.join(APP_DIR, "teams.json")) if os.path.exists(p)), None)
    if not base: raise SystemExit("no base teams.json found; pass --base")
    work = os.path.abspath(a.work) if a.work else tempfile.mkdtemp(prefix="simulig-data-")
    os.makedirs(work, exist_ok=True)
    stage = os.path.join(work, "stage")
    shutil.rmtree(stage, ignore_errors=True); os.makedirs(stage)
    log(f"work {work}\nbase {base}\nout  {out}")
    logf = open(os.path.join(work, "update.log"), "w", encoding="utf-8")
    if a.squads_only:
        return squads_only(a, out, work, stage, logf)
    try:
        if not a.offline:
            log("\n== downloads"); fetch_all(work)
        T, S = os.path.join(stage, "teams.json"), os.path.join(stage, "season-tr-superlig.json")
        shutil.copy(base, T)
        o = run("build_catalog.py", [work, T, T], logf)
        wiki = "1. Lig source: wikipedia" in o
        log("1. Lig: " + ("Wikipedia results (joint fit with the Süper Lig)" if wiki else "FALLBACK table"))
        for line in o.splitlines():
            if line.startswith(("T1 + 1. Lig joint", "  ok", "  warn", "WARNING")): log(line)
        if not wiki and a.strict_wiki: raise Fail("1. Lig Wikipedia data unavailable (--strict-wiki)")
        o = run("national_fit.py", [os.path.join(work, "results.csv"), T, T], logf)
        log("\n".join(l for l in o.splitlines() if "national teams, latest" in l or l.startswith(("home advantage", "level L"))))
        o = run("make_season.py", [os.path.join(work, "T1_2627.csv"), S], logf); log(o.splitlines()[0])
        o = run("calibrate_goals.py", [work, T], logf); log(o.rstrip())
        teams, season = json.load(open(T, encoding="utf-8")), json.load(open(S, encoding="utf-8"))
        squads_step(work, T, stage, out, a, logf)
        errs = validate(teams, season, json.load(open(base, encoding="utf-8")))
        errs += validate_squads(os.path.join(stage, "squads.json"), teams)
        if errs:
            for e in errs: log("  INVALID:", e)
            raise Fail(f"{len(errs)} validation errors")
        log("\n== validation passed")
    except Fail as e:
        log(f"\nFAILED: {e}\nnothing written (log: {os.path.join(work, 'update.log')})")
        return 1
    finally:
        logf.close()

    # Unchanged data (ignoring the snapshot timestamp)? Then leave everything as it is.
    def same(name):
        p = os.path.join(out, name)
        if not os.path.exists(p): return False
        old, new = json.load(open(p, encoding="utf-8")), json.load(open(os.path.join(stage, name), encoding="utf-8"))
        for d in (old, new): d.pop("updatedAt", None); d.pop("version", None); d.pop("generatedAt", None)
        return old == new
    if not a.force and all(same(n) for n in FILES) and os.path.exists(os.path.join(out, "manifest.json")):
        log("no data changes; nothing written")
        write_out(stage, out, json.load(open(os.path.join(out, "manifest.json")))["version"])  # for --app
    else:
        now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        version = int(now.strftime("%Y%m%d%H"))
        mp = os.path.join(out, "manifest.json")
        if os.path.exists(mp):
            try:
                version = max(version, int(json.load(open(mp))["version"]) + 1)
            except (ValueError, KeyError, TypeError):
                pass
        # The catalog (and squads.json) carry the data version so the app can compare its bundled copy with a download.
        write_out(stage, out, version)
        manifest = dict(version=version, generatedAt=now.strftime("%Y-%m-%dT%H:%M:%SZ"), season=SEASON,
                        superLigWeek=season["state"]["week"], files={n: sha256(os.path.join(stage, n)) for n in FILES})
        json.dump(manifest, open(os.path.join(stage, "manifest.json"), "w"), indent=1)
        os.makedirs(out, exist_ok=True)
        for n in FILES + ["manifest.json"]:
            shutil.copy(os.path.join(stage, n), os.path.join(out, n + ".tmp"))
        for n in FILES + ["manifest.json"]:
            os.replace(os.path.join(out, n + ".tmp"), os.path.join(out, n))
        log(f"wrote {out}: version {version}, Süper Lig week {manifest['superLigWeek']}")
    if a.app:
        if not os.path.isdir(a.app_dir): raise SystemExit(f"--app: {a.app_dir} not found")
        for n in FILES:
            shutil.copy(os.path.join(stage, n), os.path.join(a.app_dir, n))
        log(f"copied {', '.join(FILES)} into {a.app_dir}")
    if not a.work: shutil.rmtree(work, ignore_errors=True)
    return 0


def squads_only(a, out, work, stage, logf):
    """Rebuild squads.json alone. The manifest keeps its version (teams.json must match it), only the
    squads.json entry changes; squads.json gets that same version."""
    mp = os.path.join(out, "manifest.json")
    T = os.path.join(out, "teams.json")
    if not (os.path.exists(mp) and os.path.exists(T)): raise SystemExit(f"--squads-only needs {mp} and {T}")
    manifest = json.load(open(mp, encoding="utf-8"))
    teams = json.load(open(T, encoding="utf-8"))
    try:
        a.strict_squads = True
        squads_step(work, T, stage, out, a, logf)
        errs = validate_squads(os.path.join(stage, "squads.json"), teams)
        if errs:
            for e in errs: log("  INVALID:", e)
            raise Fail(f"{len(errs)} validation errors")
    except Fail as e:
        log(f"\nFAILED: {e}\nnothing written (log: {os.path.join(work, 'update.log')})")
        return 1
    finally:
        logf.close()
    Q = os.path.join(stage, "squads.json")
    d = json.load(open(Q, encoding="utf-8")); d["version"] = manifest["version"]
    json.dump(d, open(Q, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    manifest["files"]["squads.json"] = sha256(Q)
    json.dump(manifest, open(os.path.join(stage, "manifest.json"), "w"), indent=1)
    for n in ("squads.json", "manifest.json"):
        shutil.copy(os.path.join(stage, n), os.path.join(out, n + ".tmp"))
        os.replace(os.path.join(out, n + ".tmp"), os.path.join(out, n))
    log(f"wrote {out}: squads.json, manifest.json (version {manifest['version']} kept)")
    if a.app:
        if not os.path.isdir(a.app_dir): raise SystemExit(f"--app: {a.app_dir} not found")
        shutil.copy(Q, os.path.join(a.app_dir, "squads.json"))
        log(f"copied squads.json into {a.app_dir}")
    if not a.work: shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
