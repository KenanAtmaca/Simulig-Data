"""TFF 1. Lig match results from Turkish Wikipedia (raw wikitext via action=raw).

The results grid lives either on the season page itself ({{#invoke:Spor sonuçları ...}})
or in the standings template "Şablon:<season> 1. Lig puan durumu" (show_matches=only).
Both use the same keys: |match_HOME_AWAY=2-1, team names come from |name_CODE=[[...]].

    python3 lig1_wiki.py <data-dir> [--fetch]     # parse (and optionally download) + validate

fetch(data_dir) writes wiki_<season>_page.txt and wiki_<season>_tpl.txt into data_dir.
load(data_dir) returns {"seasons": {season: [match, ...]}, "checks": [...], "warnings": [...]}
and raises Lig1Error when the data is unusable (build_catalog then uses its fallback table).
"""
import datetime as dt, json, os, re, sys, urllib.parse, urllib.request

SEASONS = ["2025-26", "2026-27"]
# First matchday of each season; matchdays are spread evenly from there (about 7.4 days apart).
SEASON_START = {"2025-26": dt.date(2025, 8, 8), "2026-27": dt.date(2026, 8, 7)}
DAYS_PER_WEEK = 275 / 37
UA = "SimuligDataPipeline/1.0 (weekly data update script)"
WIKI = "https://tr.wikipedia.org/w/index.php?title={}&action=raw"

# Wikipedia team names (display text or link target) -> catalog id. Ids starting with "x-"
# are clubs that are not in the app catalog; they only help the fit.
NAMES = {
    "Kayserispor": "tr-kay", "Antalyaspor": "tr-ant", "Antalyaspor (futbol takımı)": "tr-ant",
    "Fatih Karagümrük": "tr-fkg", "Fatih Karagümrük SK": "tr-fkg",
    "Amed": "tr-amd", "Amed SFK": "tr-amd", "Amedspor": "tr-amd",
    "Çorum": "tr-cor", "Çorum FK": "tr-cor",
    "Erzurumspor": "tr-erz", "Erzurumspor FK": "tr-erz",
    "Bursaspor": "tr1-bur", "Bursaspor (futbol takımı)": "tr1-bur",
    "Iğdır": "tr1-igd", "Iğdır FK": "tr1-igd",
    "Mardin 1969": "tr1-mar", "Mardin 1969 SK": "tr1-mar",
    "Batman Petrolspor": "tr1-bat",
    "Ankara Keçiörengücü": "tr1-kec", "Ankara Keçiörengücü SK": "tr1-kec", "Keçiörengücü": "tr1-kec",
    "Bodrum": "tr1-bod", "Bodrum FK": "tr1-bod", "Bodrumspor": "tr1-bod",
    "Esenler Erokspor": "tr1-ero", "Erokspor": "tr1-ero",
    "Muğlaspor": "tr1-mug",
    "Ümraniyespor": "tr1-umr",
    "Sarıyer": "tr1-sar", "Sarıyer SK": "tr1-sar",
    "Vanspor": "tr1-van", "Vanspor FK": "tr1-van",
    "Bandırmaspor": "tr1-ban",
    "Pendikspor": "tr1-pen",
    "Manisa": "tr1-man", "Manisa FK": "tr1-man",
    "Sivasspor": "tr1-siv",
    "İstanbulspor": "tr1-ist",
    "Boluspor": "tr1-bol",
    "Adana Demirspor": "x-ads", "Hatayspor": "x-hat", "Sakaryaspor": "x-sak", "Serikspor": "x-ser",
}


class Lig1Error(Exception):
    pass


def _get(title):
    url = WIKI.format(urllib.parse.quote(title.replace(" ", "_"), safe=":_()"))
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8")


def fetch(data_dir):
    for s in SEASONS:
        page = _get(f"{s} 1. Lig")
        open(os.path.join(data_dir, f"wiki_{s}_page.txt"), "w", encoding="utf-8").write(page)
        tpl = ""
        if f"{s} 1. Lig puan durumu" in page:
            tpl = _get(f"Şablon:{s} 1. Lig puan durumu")
        open(os.path.join(data_dir, f"wiki_{s}_tpl.txt"), "w", encoding="utf-8").write(tpl)


WEEK_RE = re.compile(r"<!--\s*(\d+)\.\s*Hafta\s*-->")
MATCH_RE = re.compile(r"\|\s*match_([^\s=|_]+)_([^\s=|_]+)\s*=\s*([^|\n]*)")
SCORE_RE = re.compile(r"^\s*(\d+)\s*[-\u2013\u2014]\s*(\d+)\s*(\(H\)|\{\{[^}]*H[^}]*\}\})?\s*$")
NAME_RE = re.compile(r"\|\s*name_([^\s=|]+)\s*=\s*\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
STAND_RE = re.compile(r"\|\s*(win|draw|loss|gf|ga)_([^\s=|]+)\s*=\s*(\d+)")
ADJ_RE = re.compile(r"\|\s*adjust_points_([^\s=|]+)\s*=\s*(-?\d+)")
RES_RE = re.compile(r"\|\s*res_([^\s=|]+)\s*=\s*([A-ZÇĞİÖŞÜ/ ]+)")


def _strip_comments(line):
    return re.sub(r"<!--.*?-->", "", line)


def parse_text(text):
    """Return (matches, names, standings, res) found in one wikitext blob."""
    matches, week = {}, None
    text = re.sub(r"<!--(?!\s*\d+\.\s*Hafta).*?-->", "", text, flags=re.S)  # drop other comments
    for line in text.splitlines():
        m = WEEK_RE.search(line)
        if m: week = int(m.group(1))
        for h, a, val in MATCH_RE.findall(_strip_comments(line)):
            sm = SCORE_RE.match(val)
            if not sm: continue  # not played yet (week marker, postponed, empty)
            matches[(h, a)] = (int(sm.group(1)), int(sm.group(2)), bool(sm.group(3)), week)
    names = {}
    for code, target, disp in NAME_RE.findall(text):
        names[code] = (target.strip(), (disp or target).strip())
    stand = {}
    for k, code, v in STAND_RE.findall(text):
        stand.setdefault(code, {})[k] = int(v)
    res = {code: [x.strip() for x in v.split("/")] for code, v in RES_RE.findall(text)}
    res["__adjust__"] = {code: int(v) for code, v in ADJ_RE.findall(text)}
    return matches, names, stand, res


def _infobox(text, key):
    m = re.search(r"\|\s*" + key + r"\s*=\s*([\d.]+)", text)
    return int(m.group(1).replace(".", "")) if m else None


def _team_id(code, names):
    if code not in names: raise Lig1Error(f"no name for code {code}")
    target, disp = names[code]
    for n in (disp, target, re.sub(r"\s*\(.*\)$", "", target)):
        if n in NAMES: return NAMES[n]
    return None


def load(data_dir, today=None):
    today = today or dt.date.today()
    out = {"seasons": {}, "checks": [], "warnings": [], "unknown": {}}
    for s in SEASONS:
        pf, tf = (os.path.join(data_dir, f"wiki_{s}_{k}.txt") for k in ("page", "tpl"))
        if not os.path.exists(pf): raise Lig1Error(f"missing {pf}")
        page = open(pf, encoding="utf-8").read()
        tpl = open(tf, encoding="utf-8").read() if os.path.exists(tf) else ""
        mp, np_, sp, rp = parse_text(page)
        mt, nt, st, rt = parse_text(tpl)
        for k in set(mp) & set(mt):
            if mp[k][:2] != mt[k][:2]: raise Lig1Error(f"{s}: conflicting result for {k}: {mp[k]} vs {mt[k]}")
        raw = {**mt, **mp}
        names = {**np_, **nt}
        if not raw: raise Lig1Error(f"{s}: no results found")
        codes = sorted({c for k in raw for c in k})
        ids = {}
        for c in codes:
            tid = _team_id(c, names)
            if tid is None:
                tid = "tr1-" + re.sub(r"[^a-z]", "", c.lower().translate(str.maketrans("çğıöşü", "cgiosu"))) or c
                out["unknown"][tid] = dict(code=c, name=names.get(c, (c, c))[1])
                out["warnings"].append(f"{s}: unknown team {names.get(c)} -> {tid}")
            ids[c] = tid
        if len(set(ids.values())) != len(ids): raise Lig1Error(f"{s}: two codes map to one team")
        start = SEASON_START.get(s, dt.date(int(s[:4]), 8, 8))
        ms = []
        for (h, a), (hg, ag, forfeit, week) in raw.items():
            if h == a: raise Lig1Error(f"{s}: self match {h}")
            d = start + dt.timedelta(days=round(((week or 1) - 1) * DAYS_PER_WEEK))
            ms.append(dict(home=ids[h], away=ids[a], hg=hg, ag=ag, forfeit=forfeit, week=week, date=min(d, today).isoformat()))
        out["seasons"][s] = ms
        adj = {**rt.get("__adjust__", {}), **rp.get("__adjust__", {})}
        out.setdefault("adjust", {})[s] = {ids[c]: v for c, v in adj.items() if c in ids}
        _validate(s, ms, ids, {**sp, **st}, {**rt, **rp}, page, out)
    return out


def _table(ms):
    t = {}
    for m in ms:
        for me, f, g in ((m["home"], m["hg"], m["ag"]), (m["away"], m["ag"], m["hg"])):
            x = t.setdefault(me, dict(p=0, w=0, d=0, l=0, gf=0, ga=0))
            x["p"] += 1; x["gf"] += f; x["ga"] += g
            x["w" if f > g else "d" if f == g else "l"] += 1
    return t


def _validate(s, ms, ids, stand, res, page, out):
    chk = out["checks"]
    t = _table(ms)
    n_teams = len(t)
    if n_teams != 20: raise Lig1Error(f"{s}: {n_teams} teams with results (expected 20)")
    pairs = {(m["home"], m["away"]) for m in ms}
    if len(pairs) != len(ms): raise Lig1Error(f"{s}: duplicate fixtures")
    games = [x["p"] for x in t.values()]
    if max(games) > 38: raise Lig1Error(f"{s}: a team has {max(games)} games")
    if max(games) - min(games) > 3: raise Lig1Error(f"{s}: uneven games per team {min(games)}..{max(games)}")
    real = [m for m in ms if not m["forfeit"]]
    gpg = sum(m["hg"] + m["ag"] for m in real) / max(1, len(real))
    if not 1.8 <= gpg <= 3.8: raise Lig1Error(f"{s}: implausible goals per game {gpg:.2f}")
    chk.append(f"{s}: {len(ms)} matches ({len(ms) - len(real)} forfeits), games per team {min(games)}..{max(games)}, goals/game {gpg:.2f}")
    inv = {v: k for k, v in ids.items()}
    # 1) explicit standings (win_/draw_/loss_/gf_/ga_ in the template): must match exactly
    if stand:
        bad = []
        for tid, x in t.items():
            sv = stand.get(inv[tid])
            if not sv: bad.append(f"{tid}: missing in standings"); continue
            got = (x["w"], x["d"], x["l"], x["gf"], x["ga"])
            want = tuple(sv.get(k) for k in ("win", "draw", "loss", "gf", "ga"))
            if got != want: bad.append(f"{tid}: parsed {got} page {want}")
        if bad: raise Lig1Error(f"{s}: standings mismatch: " + "; ".join(bad))
        chk.append(f"{s}: W/D/L/GF/GA of all 20 teams equal the standings table on the page")
    # 2) week-by-week result strips (res_CODE=EG/DB/...): W/D/L per team (soft check, may lag)
    if any(k != "__adjust__" for k in res):
        bad = []
        for tid, x in t.items():
            strip = [r for r in res.get(inv[tid], []) if r] if isinstance(res.get(inv[tid]), list) else []
            w = sum(r.endswith("G") for r in strip); d = sum(r.endswith("B") for r in strip); l = sum(r.endswith("Y") for r in strip)
            if (w, d, l) != (x["w"], x["d"], x["l"]): bad.append(f"{tid} parsed {x['w']}/{x['d']}/{x['l']} strip {w}/{d}/{l}")
        if bad: out["warnings"].append(f"{s}: result strip differs: " + "; ".join(bad))
        else: chk.append(f"{s}: W/D/L of all teams equal the weekly result strips (points table derived from them matches)")
    # 3) infobox totals (soft)
    tm, tg = _infobox(page, "toplammaç"), _infobox(page, "toplamgol")
    if tm is not None:
        goals = sum(m["hg"] + m["ag"] for m in ms)
        if (tm, tg) == (len(ms), goals): chk.append(f"{s}: infobox totals match ({tm} matches, {tg} goals)")
        else: out["warnings"].append(f"{s}: infobox says {tm} matches / {tg} goals, parsed {len(ms)} / {goals}")


def table_rows(ms, adjust=None):
    """Points table [(id, p, w, d, l, gf, ga, pts)] sorted by points, goal difference, goals."""
    t = _table(ms)
    rows = [(k, x["p"], x["w"], x["d"], x["l"], x["gf"], x["ga"], 3 * x["w"] + x["d"] + (adjust or {}).get(k, 0)) for k, x in t.items()]
    return sorted(rows, key=lambda r: (-r[7], -(r[5] - r[6]), -r[5]))


if __name__ == "__main__":
    d = sys.argv[1]
    if "--fetch" in sys.argv: fetch(d)
    r = load(d)
    for c in r["checks"]: print("ok  ", c)
    for w in r["warnings"]: print("warn", w)
    for s, ms in r["seasons"].items():
        print(f"\n{s}")
        for row in table_rows(ms, r.get("adjust", {}).get(s)):
            print("  {:8s} {:2d} {:2d}-{:2d}-{:2d} {:3d}:{:<3d} {:3d}".format(*row))
    json.dump(r, open(os.path.join(d, "lig1_matches.json"), "w"), ensure_ascii=False, indent=0)
