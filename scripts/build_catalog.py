"""Rebuild the club part of teams.json from real 2025-26 + 2026-27 results.

Within each league: weighted Poisson model log(mu) = c + h*home + atk_i - def_j,
target = goals (2025-26) or 0.4*goals + 0.6*xG (2026-27), time-decayed, shrunk
toward the league mean. Coefficients map to the engine's scale exactly:
rating = league_level + coefficient / 0.035 (ExpectedGoals uses exp(0.035*(r-75))).
League levels come from average club Elo per league converted with the same
Poisson model, so cross-league matches stay consistent.

Süper Lig + TFF 1. Lig are fitted as one connected model: 1. Lig results are parsed from
Turkish Wikipedia (lig1_wiki.py, raw files in the data folder or fetched on demand) and
the clubs that moved between the divisions link the two levels. The joint fit is shifted
so the Süper Lig keeps its Elo-anchored level. If the Wikipedia data is missing or fails
validation, the hardcoded 1. Lig table below is used instead (anchored on the relegated sides).

    python3 build_catalog.py <data-dir> <teams.json in> [teams.json out] [--no-wiki]
"""
import csv, json, math, os, sys, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.dont_write_bytecode = True  # keep the scripts folder clean when importing lig1_wiki

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
DATA = ARGS[0]
TEAMS_JSON = ARGS[1]
OUT_JSON = ARGS[2] if len(ARGS) > 2 else None
USE_WIKI = "--no-wiki" not in sys.argv
# Reference date for the time decay: today, or SIMULIG_TODAY=YYYY-MM-DD for reproducible runs.
TODAY = dt.date.fromisoformat(os.environ["SIMULIG_TODAY"]) if os.environ.get("SIMULIG_TODAY") else dt.date.today()
HALF_LIFE = 210.0
SLOPE = 0.035
SHRINK = 6.0  # pseudo-matches pulling each team toward the league mean

# fd name -> (id, display name, short, primary, secondary)
M = {
 "T1": ("tr-superlig", {
  "Galatasaray": ("tr-gs", "Galatasaray", "GS", "#A90432", "#FDB912"),
  "Fenerbahce": ("tr-fb", "Fenerbahçe", "FB", "#0E1E5B", "#FFED00"),
  "Besiktas": ("tr-bjk", "Beşiktaş", "BJK", "#111111", "#FFFFFF"),
  "Trabzonspor": ("tr-ts", "Trabzonspor", "TS", "#6D1A36", "#5BC2E7"),
  "Buyuksehyr": ("tr-ibfk", "Başakşehir", "İBFK", "#E35205", "#002855"),
  "Samsunspor": ("tr-sam", "Samsunspor", "SAM", "#E30613", "#FFFFFF"),
  "Goztep": ("tr-goz", "Göztepe", "GÖZ", "#FFD100", "#E30613"),
  "Alanyaspor": ("tr-aln", "Alanyaspor", "ALN", "#F39200", "#00843D"),
  "Konyaspor": ("tr-kon", "Konyaspor", "KON", "#00843D", "#FFFFFF"),
  "Kasimpasa": ("tr-kas", "Kasımpaşa", "KAS", "#1B3C8C", "#FFFFFF"),
  "Gaziantep": ("tr-gfk", "Gaziantep FK", "GFK", "#D71920", "#111111"),
  "Rizespor": ("tr-riz", "Rizespor", "RİZ", "#00843D", "#0055A4"),
  "Eyupspor": ("tr-eyp", "Eyüpspor", "EYP", "#6A1B9A", "#FFD600"),
  "Kocaelispor": ("tr-koc", "Kocaelispor", "KOC", "#00843D", "#111111"),
  "Genclerbirligi": ("tr-gb", "Gençlerbirliği", "GB", "#E30613", "#111111"),
  "Amedspor": ("tr-amd", "Amedspor", "AMD", "#00843D", "#E30613"),
  "Corum": ("tr-cor", "Çorum FK", "ÇOR", "#E30613", "#111111"),
  "Erzurumspor": ("tr-erz", "Erzurumspor", "ERZ", "#0055A4", "#FFFFFF"),
  # relegated after 2025-26, rated from last season then moved to 1. Lig
  "Antalyaspor": ("tr-ant", "Antalyaspor", "ANT", "#E30613", "#FFFFFF"),
  "Kayserispor": ("tr-kay", "Kayserispor", "KAY", "#E30613", "#FFD100"),
  "Karagumruk": ("tr-fkg", "Fatih Karagümrük", "FKG", "#C8102E", "#111111"),
 }),
 "E0": ("eng-premier", {
  "Arsenal": ("eng-ars", "Arsenal", "ARS", "#EF0107", "#FFFFFF"),
  "Aston Villa": ("eng-avl", "Aston Villa", "AVL", "#670E36", "#95BFE5"),
  "Bournemouth": ("eng-bou", "Bournemouth", "BOU", "#DA291C", "#111111"),
  "Brentford": ("eng-bre", "Brentford", "BRE", "#E30613", "#FFFFFF"),
  "Brighton": ("eng-bha", "Brighton", "BHA", "#0057B8", "#FFFFFF"),
  "Chelsea": ("eng-che", "Chelsea", "CHE", "#034694", "#FFFFFF"),
  "Coventry": ("eng-cov", "Coventry City", "COV", "#59CBE8", "#FFFFFF"),
  "Crystal Palace": ("eng-cry", "Crystal Palace", "CRY", "#1B458F", "#C4122E"),
  "Everton": ("eng-eve", "Everton", "EVE", "#003399", "#FFFFFF"),
  "Fulham": ("eng-ful", "Fulham", "FUL", "#FFFFFF", "#111111"),
  "Hull": ("eng-hul", "Hull City", "HUL", "#F5A12D", "#111111"),
  "Ipswich": ("eng-ips", "Ipswich Town", "IPS", "#3A64A3", "#FFFFFF"),
  "Leeds": ("eng-lee", "Leeds United", "LEE", "#FFFFFF", "#1D428A"),
  "Liverpool": ("eng-liv", "Liverpool", "LIV", "#C8102E", "#F6EB61"),
  "Man City": ("eng-mci", "Manchester City", "MCI", "#6CABDD", "#1C2C5B"),
  "Man United": ("eng-mun", "Manchester United", "MUN", "#DA291C", "#FBE122"),
  "Newcastle": ("eng-new", "Newcastle United", "NEW", "#241F20", "#FFFFFF"),
  "Nott'm Forest": ("eng-nfo", "Nottingham Forest", "NFO", "#DD0000", "#FFFFFF"),
  "Sunderland": ("eng-sun", "Sunderland", "SUN", "#EB172B", "#FFFFFF"),
  "Tottenham": ("eng-tot", "Tottenham", "TOT", "#FFFFFF", "#132257"),
 }),
 "SP1": ("esp-laliga", {
  "Alaves": ("esp-ala", "Alavés", "ALA", "#0761AF", "#FFFFFF"),
  "Ath Bilbao": ("esp-ath", "Athletic Bilbao", "ATH", "#EE2523", "#FFFFFF"),
  "Ath Madrid": ("esp-atm", "Atlético Madrid", "ATM", "#CB3524", "#272E61"),
  "Barcelona": ("esp-bar", "Barcelona", "BAR", "#A50044", "#004D98"),
  "Betis": ("esp-bet", "Real Betis", "BET", "#00954C", "#FFFFFF"),
  "Celta": ("esp-cel", "Celta Vigo", "CEL", "#8AC3EE", "#FFFFFF"),
  "Elche": ("esp-elc", "Elche", "ELC", "#05642C", "#FFFFFF"),
  "Espanol": ("esp-esp", "Espanyol", "ESP", "#007FC8", "#FFFFFF"),
  "Getafe": ("esp-get", "Getafe", "GET", "#005999", "#FFFFFF"),
  "La Coruna": ("esp-dep", "Deportivo La Coruña", "DEP", "#0067B1", "#FFFFFF"),
  "Levante": ("esp-lev", "Levante", "LEV", "#B4053F", "#004D98"),
  "Malaga": ("esp-mal", "Málaga", "MAL", "#0080C8", "#FFFFFF"),
  "Osasuna": ("esp-osa", "Osasuna", "OSA", "#D91A21", "#0A346F"),
  "Real Madrid": ("esp-rma", "Real Madrid", "RMA", "#FFFFFF", "#FEBE10"),
  "Santander": ("esp-rac", "Racing Santander", "RAC", "#00843D", "#FFFFFF"),
  "Sevilla": ("esp-sev", "Sevilla", "SEV", "#FFFFFF", "#D81E05"),
  "Sociedad": ("esp-rso", "Real Sociedad", "RSO", "#0067B1", "#FFFFFF"),
  "Valencia": ("esp-val", "Valencia", "VAL", "#FFFFFF", "#EE3524"),
  "Vallecano": ("esp-ray", "Rayo Vallecano", "RAY", "#FFFFFF", "#E53027"),
  "Villarreal": ("esp-vil", "Villarreal", "VIL", "#FFE667", "#005187"),
 }),
 "I1": ("ita-seriea", {
  "Atalanta": ("ita-ata", "Atalanta", "ATA", "#1E71B8", "#111111"),
  "Bologna": ("ita-bol", "Bologna", "BOL", "#1A2F48", "#A21C26"),
  "Cagliari": ("ita-cag", "Cagliari", "CAG", "#B01028", "#002350"),
  "Como": ("ita-com", "Como", "COM", "#003DA5", "#FFFFFF"),
  "Fiorentina": ("ita-fio", "Fiorentina", "FIO", "#482E92", "#FFFFFF"),
  "Frosinone": ("ita-fro", "Frosinone", "FRO", "#FFD200", "#0055A4"),
  "Genoa": ("ita-gen", "Genoa", "GEN", "#A71930", "#002E5D"),
  "Inter": ("ita-int", "Inter", "INT", "#0068A8", "#111111"),
  "Juventus": ("ita-juv", "Juventus", "JUV", "#111111", "#FFFFFF"),
  "Lazio": ("ita-laz", "Lazio", "LAZ", "#87D8F7", "#FFFFFF"),
  "Lecce": ("ita-lec", "Lecce", "LEC", "#FFD200", "#E30613"),
  "Milan": ("ita-mil", "Milan", "MIL", "#FB090B", "#111111"),
  "Monza": ("ita-mon", "Monza", "MON", "#E30613", "#FFFFFF"),
  "Napoli": ("ita-nap", "Napoli", "NAP", "#12A0D7", "#FFFFFF"),
  "Parma": ("ita-par", "Parma", "PAR", "#FFD200", "#0055A4"),
  "Roma": ("ita-rom", "Roma", "ROM", "#8E1F2F", "#F0BC42"),
  "Sassuolo": ("ita-sas", "Sassuolo", "SAS", "#00A752", "#111111"),
  "Torino": ("ita-tor", "Torino", "TOR", "#8A1E03", "#FFFFFF"),
  "Udinese": ("ita-udi", "Udinese", "UDI", "#111111", "#FFFFFF"),
  "Venezia": ("ita-ven", "Venezia", "VEN", "#111111", "#F15A22"),
 }),
 "D1": ("ger-bundesliga", {
  "Augsburg": ("ger-fca", "Augsburg", "FCA", "#BA3733", "#46714D"),
  "Bayern Munich": ("ger-bay", "Bayern München", "BAY", "#DC052D", "#FFFFFF"),
  "Dortmund": ("ger-bvb", "Borussia Dortmund", "BVB", "#FDE100", "#111111"),
  "Ein Frankfurt": ("ger-sge", "Eintracht Frankfurt", "SGE", "#E1000F", "#111111"),
  "Elversberg": ("ger-elv", "Elversberg", "ELV", "#111111", "#FFFFFF"),
  "FC Koln": ("ger-koe", "Köln", "KOE", "#ED1C24", "#FFFFFF"),
  "Freiburg": ("ger-scf", "Freiburg", "SCF", "#E30613", "#111111"),
  "Hamburg": ("ger-hsv", "Hamburg", "HSV", "#0A3F86", "#FFFFFF"),
  "Hoffenheim": ("ger-tsg", "Hoffenheim", "TSG", "#1961B5", "#FFFFFF"),
  "Leverkusen": ("ger-b04", "Bayer Leverkusen", "B04", "#E32221", "#111111"),
  "M'gladbach": ("ger-bmg", "Mönchengladbach", "BMG", "#111111", "#00A651"),
  "Mainz": ("ger-m05", "Mainz", "M05", "#C3141E", "#FFFFFF"),
  "Paderborn": ("ger-scp", "Paderborn", "PAD", "#0055A4", "#111111"),
  "RB Leipzig": ("ger-rbl", "RB Leipzig", "RBL", "#DD0741", "#FFFFFF"),
  "Schalke 04": ("ger-s04", "Schalke 04", "S04", "#004D9D", "#FFFFFF"),
  "Stuttgart": ("ger-vfb", "Stuttgart", "VFB", "#FFFFFF", "#E32219"),
  "Union Berlin": ("ger-fcu", "Union Berlin", "FCU", "#EB1923", "#FFFFFF"),
  "Werder Bremen": ("ger-svw", "Werder Bremen", "SVW", "#1D9053", "#FFFFFF"),
 }),
 "F1": ("fra-ligue1", {
  "Angers": ("fra-sco", "Angers", "SCO", "#111111", "#FFFFFF"),
  "Auxerre": ("fra-aux", "Auxerre", "AUX", "#FFFFFF", "#0055A4"),
  "Brest": ("fra-sb29", "Brest", "BRE", "#E30613", "#FFFFFF"),
  "Le Havre": ("fra-hac", "Le Havre", "HAC", "#5EB6E4", "#1A2B4C"),
  "Le Mans": ("fra-lem", "Le Mans", "LMN", "#E30613", "#FFD200"),
  "Lens": ("fra-rcl", "Lens", "RCL", "#FFD200", "#E30613"),
  "Lille": ("fra-los", "Lille", "LOS", "#E01E13", "#1A2B4C"),
  "Lorient": ("fra-fcl", "Lorient", "FCL", "#F58113", "#111111"),
  "Lyon": ("fra-ol", "Lyon", "OL", "#FFFFFF", "#DA001A"),
  "Marseille": ("fra-om", "Marseille", "OM", "#2FAEE0", "#FFFFFF"),
  "Monaco": ("fra-asm", "Monaco", "ASM", "#E30613", "#FFFFFF"),
  "Nice": ("fra-ogcn", "Nice", "NIC", "#E30613", "#111111"),
  "Paris FC": ("fra-pfc", "Paris FC", "PFC", "#1A2B4C", "#FFFFFF"),
  "Paris SG": ("fra-psg", "Paris Saint-Germain", "PSG", "#004170", "#DA291C"),
  "Rennes": ("fra-srfc", "Rennes", "REN", "#E30613", "#111111"),
  "Strasbourg": ("fra-rcsa", "Strasbourg", "STR", "#0095DA", "#FFFFFF"),
  "Toulouse": ("fra-tfc", "Toulouse", "TFC", "#6A1B9A", "#FFFFFF"),
  "Troyes": ("fra-est", "Troyes", "TRO", "#0055A4", "#FFFFFF"),
 }),
 "N1": ("ned-eredivisie", {
  "AZ Alkmaar": ("ned-az", "AZ Alkmaar", "AZ", "#DB0021", "#FFFFFF"),
  "Ajax": ("ned-aja", "Ajax", "AJA", "#D2122E", "#FFFFFF"),
  "Cambuur": ("ned-cam", "Cambuur", "CAM", "#FFD200", "#0055A4"),
  "Den Haag": ("ned-ado", "ADO Den Haag", "ADO", "#00843D", "#FFD200"),
  "Excelsior": ("ned-exc", "Excelsior", "EXC", "#E30613", "#111111"),
  "Feyenoord": ("ned-fey", "Feyenoord", "FEY", "#E30613", "#FFFFFF"),
  "For Sittard": ("ned-for", "Fortuna Sittard", "FOR", "#FFD200", "#00843D"),
  "Go Ahead Eagles": ("ned-gae", "Go Ahead Eagles", "GAE", "#E30613", "#FFD200"),
  "Groningen": ("ned-gro", "Groningen", "GRO", "#00843D", "#FFFFFF"),
  "Heerenveen": ("ned-hee", "Heerenveen", "HEE", "#0055A4", "#FFFFFF"),
  "Nijmegen": ("ned-nec", "NEC Nijmegen", "NEC", "#E30613", "#00843D"),
  "PSV Eindhoven": ("ned-psv", "PSV", "PSV", "#ED1C24", "#FFFFFF"),
  "Sparta Rotterdam": ("ned-spa", "Sparta Rotterdam", "SPA", "#E30613", "#FFFFFF"),
  "Telstar": ("ned-tel", "Telstar", "TEL", "#FFFFFF", "#E30613"),
  "Twente": ("ned-twe", "Twente", "TWE", "#E30613", "#FFFFFF"),
  "Utrecht": ("ned-utr", "Utrecht", "UTR", "#E30613", "#FFFFFF"),
  "Willem II": ("ned-wil", "Willem II", "WIL", "#E30613", "#0055A4"),
  "Zwolle": ("ned-pec", "PEC Zwolle", "PEC", "#0055A4", "#FFFFFF"),
 }),
 "P1": ("por-liga", {
  "Academico Viseu": ("por-avi", "Académico de Viseu", "AVI", "#111111", "#FFFFFF"),
  "Alverca": ("por-alv", "Alverca", "ALV", "#E30613", "#FFFFFF"),
  "Arouca": ("por-aro", "Arouca", "ARO", "#FFD200", "#0055A4"),
  "Benfica": ("por-slb", "Benfica", "SLB", "#E83030", "#FFFFFF"),
  "Casa Pia": ("por-cpi", "Casa Pia", "CPI", "#111111", "#FFFFFF"),
  "Estoril": ("por-est", "Estoril", "EST", "#FFD200", "#0055A4"),
  "Estrela": ("por-ama", "Estrela da Amadora", "EAM", "#E30613", "#00843D"),
  "Famalicao": ("por-fam", "Famalicão", "FAM", "#0055A4", "#FFFFFF"),
  "Gil Vicente": ("por-gil", "Gil Vicente", "GIL", "#E30613", "#0055A4"),
  "Guimaraes": ("por-vsc", "Vitória Guimarães", "VSC", "#FFFFFF", "#111111"),
  "Maritimo": ("por-mar", "Marítimo", "MAR", "#E30613", "#00843D"),
  "Moreirense": ("por-mor", "Moreirense", "MOR", "#00843D", "#FFFFFF"),
  "Nacional": ("por-nac", "Nacional", "NAC", "#111111", "#FFFFFF"),
  "Porto": ("por-fcp", "Porto", "FCP", "#00428C", "#FFFFFF"),
  "Rio Ave": ("por-rio", "Rio Ave", "RAV", "#00843D", "#FFFFFF"),
  "Santa Clara": ("por-scl", "Santa Clara", "SCL", "#E30613", "#FFFFFF"),
  "Sp Braga": ("por-bra", "Braga", "BRA", "#E30613", "#FFFFFF"),
  "Sp Lisbon": ("por-scp", "Sporting", "SCP", "#008057", "#FFFFFF"),
 }),
}

# Average club Elo per top flight (reference level, 2025-26) and the scale midpoint.
LEAGUE_ELO = {"E0": 1790, "SP1": 1720, "I1": 1715, "D1": 1705, "F1": 1640, "N1": 1585, "P1": 1570, "T1": 1555}
ELO_PIVOT = 1650


def poisson_pmf(k, l):
    return math.exp(-l) * l ** k / math.factorial(k)


def expected_score(log_ratio, base=1.33):
    """Win + half draw for side A when log(muA/muB) = log_ratio, neutral venue."""
    la, lb = base * math.exp(log_ratio / 2), base * math.exp(-log_ratio / 2)
    pa = [poisson_pmf(k, la) for k in range(12)]
    pb = [poisson_pmf(k, lb) for k in range(12)]
    win = sum(pa[i] * pb[j] for i in range(12) for j in range(12) if i > j)
    draw = sum(pa[i] * pb[i] for i in range(12))
    return win + draw / 2


def rating_points_per_elo():
    # Find the overall-rating gap whose goal ratio gives the same expected score as +100 Elo.
    target = 1 / (1 + 10 ** (-100 / 400))
    lo, hi = 0.0, 20.0
    for _ in range(60):
        mid = (lo + hi) / 2
        # neutral match, both sides' attack and defence differ by mid -> log ratio = 2*SLOPE*mid
        if expected_score(2 * SLOPE * mid) < target: lo = mid
        else: hi = mid
    return lo / 100


def load(code, season):
    rows = list(csv.DictReader(open(f"{DATA}/{code}_{season}.csv", encoding="utf-8-sig")))
    out = []
    for r in rows:
        if not r.get("HomeTeam") or r.get("FTHG", "") == "": continue
        d = dt.datetime.strptime(r["Date"], "%d/%m/%Y").date()
        hg, ag = float(r["FTHG"]), float(r["FTAG"])
        if r.get("HxG"):
            hg = 0.4 * hg + 0.6 * float(r["HxG"])
            ag = 0.4 * ag + 0.6 * float(r["AxG"])
        w = 0.5 ** ((TODAY - d).days / HALF_LIFE)
        out.append((r["HomeTeam"], r["AwayTeam"], hg, ag, w))
    return out


def fit(matches, teams, prior, prior_def=None, shrink=SHRINK, tol=1e-9, max_iter=3000):
    """Weighted Poisson fit by block coordinate ascent (exact per-block updates).

    matches: (home, away, hg, ag, w) or (home, away, hg, ag, w, neutral).
    prior / prior_def: log-strength each team is shrunk toward (attack / defence);
    prior_def defaults to prior. Returns atk, dfn, home advantage (log)."""
    ms = [m if len(m) == 6 else (*m, False) for m in matches]
    pd = prior_def if prior_def is not None else prior
    atk = {t: prior.get(t, 0.0) for t in teams}
    dfn = {t: pd.get(t, 0.0) for t in teams}
    c, h = math.log(1.3), 0.25
    num = sum(w * (hg + ag) for H, A, hg, ag, w, n in ms)
    hn = sum(w * hg for H, A, hg, ag, w, n in ms if not n)
    for it in range(max_iter):
        old = (c, h, dict(atk), dict(dfn))
        den = sum(w * (math.exp((0 if n else h) + atk[H] - dfn[A]) + math.exp(atk[A] - dfn[H])) for H, A, hg, ag, w, n in ms)
        c = math.log(num / den)
        hd = sum(w * math.exp(c + atk[H] - dfn[A]) for H, A, hg, ag, w, n in ms if not n)
        if hd > 0: h = math.log(hn / hd)
        sy = {t: shrink * math.exp(prior.get(t, 0.0)) for t in teams}; sm = {t: shrink for t in teams}
        for H, A, hg, ag, w, n in ms:
            hh = 0 if n else h
            sy[H] += w * hg; sm[H] += w * math.exp(c + hh - dfn[A])
            sy[A] += w * ag; sm[A] += w * math.exp(c - dfn[H])
        for t in teams: atk[t] = math.log(sy[t] / sm[t])
        # defence: goals conceded = exp(c + atk_opp - def_t)
        sy = {t: shrink * math.exp(-pd.get(t, 0.0)) for t in teams}; sm = {t: shrink for t in teams}
        for H, A, hg, ag, w, n in ms:
            hh = 0 if n else h
            sy[H] += w * ag; sm[H] += w * math.exp(c + atk[A])
            sy[A] += w * hg; sm[A] += w * math.exp(c + hh + atk[H])
        for t in teams: dfn[t] = -math.log(sy[t] / sm[t])
        delta = max([abs(c - old[0]), abs(h - old[1])] + [abs(atk[t] - old[2][t]) for t in teams] + [abs(dfn[t] - old[3][t]) for t in teams])
        if delta < tol: break
    return atk, dfn, h


def club(tid, name, short, comp, a, d, colors, country="TR"):
    return dict(id=tid, name=name, short=short, country=country, competition=comp, kind="club", attack=a, defence=d, colors=list(colors))


# 1. Lig fallback: 2026-27 table (8 Nov 2026, TFF via Wikipedia): played, gf, ga.
# Also the source of names, short codes and colours for the 1. Lig clubs.
LIG1_FALLBACK = [
    ("tr1-bur", "Bursaspor", "BUR", "#00843D", "#FFFFFF", 14, 30, 12),
    ("tr-kay", "Kayserispor", "KAY", "#E30613", "#FFD100", 14, 33, 11),
    ("tr1-igd", "Iğdır FK", "IĞD", "#E30613", "#0055A4", 14, 19, 11),
    ("tr1-mar", "Mardin 1969", "MAR", "#E30613", "#FFD200", 14, 19, 13),
    ("tr1-bat", "Batman Petrolspor", "BAT", "#E30613", "#111111", 14, 27, 24),
    ("tr1-kec", "Keçiörengücü", "KEÇ", "#6A1B9A", "#FFFFFF", 14, 26, 18),
    ("tr1-bod", "Bodrum FK", "BOD", "#00843D", "#FFFFFF", 14, 18, 13),
    ("tr-ant", "Antalyaspor", "ANT", "#E30613", "#FFFFFF", 14, 20, 21),
    ("tr-fkg", "Fatih Karagümrük", "FKG", "#C8102E", "#111111", 14, 20, 16),
    ("tr1-ero", "Esenler Erokspor", "ERO", "#FFD100", "#111111", 14, 20, 18),
    ("tr1-mug", "Muğlaspor", "MUĞ", "#0055A4", "#FFFFFF", 14, 18, 25),
    ("tr1-umr", "Ümraniyespor", "ÜMR", "#E30613", "#0E1E5B", 13, 16, 12),
    ("tr1-sar", "Sarıyer", "SAR", "#0E1E5B", "#FFFFFF", 14, 15, 19),
    ("tr1-van", "Vanspor", "VAN", "#E30613", "#111111", 14, 17, 23),
    ("tr1-ban", "Bandırmaspor", "BAN", "#E30613", "#0055A4", 14, 17, 17),
    ("tr1-pen", "Pendikspor", "PEN", "#E30613", "#FFFFFF", 14, 15, 25),
    ("tr1-man", "Manisa FK", "MAN", "#111111", "#FFFFFF", 14, 21, 24),
    ("tr1-siv", "Sivasspor", "SİV", "#E30613", "#FFFFFF", 14, 17, 23),
    ("tr1-ist", "İstanbulspor", "İST", "#FFD100", "#111111", 14, 12, 33),
    ("tr1-bol", "Boluspor", "BOL", "#E30613", "#FFFFFF", 13, 6, 28),
]


def lig1_fallback(tr_super_fit):
    """Old heuristic: 1. Lig goals table anchored on the three relegated sides."""
    lig1 = LIG1_FALLBACK
    games = sum(r[5] for r in lig1) / 2
    avg = sum(r[6] for r in lig1) / (2 * games)  # goals per team per game
    shrink = 8.0
    rel = {}
    for tid, name, short, p, s, pl, gf, ga in lig1:
        a = math.log((gf + shrink * avg) / ((pl + shrink) * avg))
        d = -math.log((ga + shrink * avg) / ((pl + shrink) * avg))
        rel[tid] = (a / SLOPE, d / SLOPE)
    # Anchor: the three relegated sides' 2025-26 Süper Lig ratings, minus a season of drift.
    anchors = {"tr-ant": "Antalyaspor", "tr-kay": "Kayserispor", "tr-fkg": "Karagumruk"}
    diffs = []
    for tid, fd in anchors.items():
        sa, sd = tr_super_fit[fd]
        ra, rd = rel[tid]
        diffs.append(((sa + sd) / 2) - ((ra + rd) / 2))
    lig1_level = sum(diffs) / len(diffs) - 1.0
    print(f"\n1. Lig level {lig1_level:.1f} (fallback table)")
    out = []
    for tid, name, short, p, s, pl, gf, ga in lig1:
        a, d = lig1_level + rel[tid][0], lig1_level + rel[tid][1]
        print(f"  {name:18s} {a:5.1f} {d:5.1f}")
        out.append(club(tid, name, short, "tr-1lig", a, d, (p, s)))
    return out


def turkey_joint(level, catalog):
    """Süper Lig + 1. Lig as one model. Returns (super_clubs, lig1_clubs) or raises."""
    import lig1_wiki
    if not os.path.exists(os.path.join(DATA, "wiki_2026-27_page.txt")):
        print("fetching 1. Lig pages from Wikipedia")
        lig1_wiki.fetch(DATA)
    w = lig1_wiki.load(DATA, TODAY)
    for c in w["checks"]: print("  ok  ", c)
    for x in w["warnings"]: print("  warn", x)
    comp, names = M["T1"]
    fd2id = {k: v[0] for k, v in names.items()}
    matches, division = [], {}
    for season in ("2526", "2627"):
        for H, A, hg, ag, wt in load("T1", season):
            if H not in fd2id or A not in fd2id: raise SystemExit(f"missing mapping for T1 {H} / {A}")
            matches.append((fd2id[H], fd2id[A], hg, ag, wt))
            division[(fd2id[H], season)] = division[(fd2id[A], season)] = "S"
    for season, key in (("2025-26", "2526"), ("2026-27", "2627")):
        for m in w["seasons"][season]:
            division[(m["home"], key)] = division[(m["away"], key)] = "1"
            if m["forfeit"]: continue  # awarded 3-0, not a football result
            d = dt.date.fromisoformat(m["date"])
            wt = 0.5 ** ((TODAY - d).days / HALF_LIFE)
            matches.append((m["home"], m["away"], float(m["hg"]), float(m["ag"]), wt))
    teams = sorted({m[0] for m in matches} | {m[1] for m in matches})
    cur_div = {}
    for (t, season), dv in sorted(division.items(), key=lambda x: x[0][1]):
        cur_div[t] = dv  # 2026-27 division wins over 2025-26
    current_s = sorted(t for t in teams if division.get((t, "2627")) == "S")
    current_1 = sorted(t for t in teams if division.get((t, "2627")) == "1")
    if len(current_s) != 18 or len(current_1) != 20:
        raise lig1_wiki.Lig1Error(f"division sizes {len(current_s)} / {len(current_1)}")
    movers = sorted(t for t in teams if division.get((t, "2526")) and division.get((t, "2627")) and division[(t, "2526")] != division[(t, "2627")])
    print("  clubs linking the divisions:", ", ".join(movers))
    if len(movers) < 2: raise lig1_wiki.Lig1Error("divisions are not connected")
    # Pass 1: shrink toward 0; pass 2: shrink each club toward its own division's mean.
    atk, dfn, h = fit(matches, teams, {})
    prior_a, prior_d = {}, {}
    for dv in ("S", "1"):
        grp = [t for t in teams if cur_div[t] == dv]
        ma = sum(atk[t] for t in grp) / len(grp); md = sum(dfn[t] for t in grp) / len(grp)
        for t in grp: prior_a[t], prior_d[t] = ma, md
    # Clubs promoted from the 2. Lig (no 2025-26 data in either division) start a little below
    # the 1. Lig mean, like promoted sides in the other leagues.
    for t in current_1:
        if (t, "2526") not in division:
            prior_a[t] -= 0.12; prior_d[t] -= 0.12
    atk, dfn, h = fit(matches, teams, prior_a, prior_d)
    ma = sum(atk[t] for t in current_s) / len(current_s)
    md = sum(dfn[t] for t in current_s) / len(current_s)
    rate = {t: (level + (atk[t] - ma) / SLOPE, level + (dfn[t] - md) / SLOPE) for t in teams}
    l1 = [rate[t] for t in current_1]
    lig1_level = sum((a + d) / 2 for a, d in l1) / len(l1)
    print(f"\nT1 + 1. Lig joint fit: Süper Lig level {level:.1f}, 1. Lig level {lig1_level:.1f}"
          f" (gap {level - lig1_level:.1f}), home adv x{math.exp(h):.2f}")
    id2fd = {v[0]: (k, v) for k, v in names.items()}
    supers = []
    for t in sorted(current_s, key=lambda t: -sum(rate[t])):
        a, d = rate[t]
        print(f"  S {t:9s} {a:5.1f} {d:5.1f}")
        fd, (tid, name, short, p, s) = id2fd[t]
        supers.append(club(tid, name, short, "tr-superlig", a, d, (p, s)))
    meta = {r[0]: r for r in LIG1_FALLBACK}
    old = {t["id"]: t for t in catalog["teams"]}
    lig1 = []
    for t in sorted(current_1, key=lambda t: -sum(rate[t])):
        a, d = rate[t]
        if t in meta:
            _, name, short, p, s, *_ = meta[t]
        elif t in old:
            name, short, (p, s) = old[t]["name"], old[t]["short"], old[t]["colors"]
        elif t in id2fd:
            name, short, p, s = id2fd[t][1][1:]
        else:
            u = w["unknown"].get(t, {})
            name, short, p, s = u.get("name", t), u.get("code", t[-3:].upper())[:4], "#E30613", "#FFFFFF"
            print(f"  NEW 1. Lig club {t} ({name}): default short code and colours")
        print(f"  1 {t:9s} {a:5.1f} {d:5.1f}  {name}")
        lig1.append(club(t, name, short, "tr-1lig", a, d, (p, s)))
    gone = sorted(t for t in teams if t not in current_s and t not in current_1)
    print("  fitted but not in 2026-27 (link only):", ", ".join(f"{t} {sum(rate[t]) / 2:.1f}" for t in gone))
    return supers, lig1


def main():
    catalog = json.load(open(TEAMS_JSON))
    k = rating_points_per_elo()
    print(f"rating points per 100 Elo: {k * 100:.2f}")
    new_clubs = []
    levels = {}
    tr_super_fit = {}
    for code, (comp, names) in M.items():
        m = load(code, "2526") + load(code, "2627")
        current = sorted({H for H, *_ in load(code, "2627")} | {A for _, A, *_ in load(code, "2627")})
        everyone = sorted({H for H, *_ in m} | {A for _, A, *_ in m})
        # Promoted sides (no 2025-26 data in this league) start a little below average.
        last = {H for H, *_ in load(code, "2526")}
        prior = {t: (-0.12 if t not in last else 0.0) for t in everyone}
        atk, dfn, h = fit(m, everyone, prior)
        ma = sum(atk[t] for t in current) / len(current)
        md = sum(dfn[t] for t in current) / len(current)
        level = 75 + (LEAGUE_ELO[code] - ELO_PIVOT) * k
        levels[code] = level
        print(f"\n{code} level {level:.1f}  home adv x{math.exp(h):.2f}")
        rated = []
        for t in everyone:
            a = level + (atk[t] - ma) / SLOPE
            d = level + (dfn[t] - md) / SLOPE
            rated.append((t, a, d))
        for t, a, d in sorted(rated, key=lambda x: -(x[1] + x[2])):
            tag = "" if t in current else "  (not in 2026-27)"
            print(f"  {t:18s} {a:5.1f} {d:5.1f}{tag}")
        for t, a, d in rated:
            if code == "T1": tr_super_fit[t] = (a, d)
            if t not in current: continue
            if t not in names: raise SystemExit(f"missing mapping for {code} {t}")
            tid, name, short, p, s = names[t]
            new_clubs.append(club(tid, name, short, comp, a, d, (p, s),
                                  {"tr": "TR", "eng": "GB", "esp": "ES", "ita": "IT", "ger": "DE", "fra": "FR", "ned": "NL", "por": "PT"}[comp.split("-")[0]]))
    lig1_source = "fallback"
    if USE_WIKI:
        try:
            supers, lig1 = turkey_joint(levels["T1"], catalog)
            # keep the previous file order: Süper Lig first (football-data name order), 1. Lig last
            fd_order = {v[0]: k for k, v in M["T1"][1].items()}
            supers.sort(key=lambda t: fd_order[t["id"]])
            l1_order = {r[0]: i for i, r in enumerate(LIG1_FALLBACK)}
            lig1.sort(key=lambda t: l1_order.get(t["id"], len(l1_order)))
            new_clubs = supers + [t for t in new_clubs if t["competition"] != "tr-superlig"] + lig1
            lig1_source = "wikipedia"
        except Exception as e:  # any parsing/validation problem -> keep the old heuristic
            print(f"\nWARNING: 1. Lig from Wikipedia failed ({type(e).__name__}: {e}); using the fallback table")
    if lig1_source == "fallback":
        new_clubs += lig1_fallback(tr_super_fit)
    print(f"\n1. Lig source: {lig1_source}")
    for t in new_clubs:
        t["attack"] = int(round(min(97, max(45, t["attack"]))))
        t["defence"] = int(round(min(97, max(45, t["defence"]))))
    # Keep existing country codes for ids that already existed.
    old = {t["id"]: t for t in catalog["teams"]}
    for t in new_clubs:
        if t["id"] in old: t["country"] = old[t["id"]]["country"]
    keep = [t for t in catalog["teams"] if t["kind"] != "club"]
    catalog["teams"] = new_clubs + keep
    # Official tie-break order per league (points first everywhere).
    rules = {
        "eng-premier": ["pts", "gd", "gf", "h2hPts", "h2hGF"],
        "ger-bundesliga": ["pts", "gd", "gf", "h2hPts", "h2hGF"],
        "ned-eredivisie": ["pts", "gd", "gf", "h2hPts", "h2hGF"],
        "fra-ligue1": ["pts", "gd", "gf", "h2hPts", "h2hGD"],
        "esp-laliga": ["pts", "h2hPts", "h2hGD", "gd", "gf"],
        "ita-seriea": ["pts", "h2hPts", "h2hGD", "gd", "gf"],
        "por-liga": ["pts", "h2hPts", "h2hGD", "h2hGF", "gd", "gf"],
    }
    for comp in catalog["competitions"]:
        n = sum(1 for t in new_clubs if t["competition"] == comp["id"])
        if n: comp["teams"] = n
        if comp["id"] in rules: comp["tiebreak"] = rules[comp["id"]]
    if OUT_JSON:
        json.dump(catalog, open(OUT_JSON, "w"), ensure_ascii=False, indent=1)
        print("\nwrote", OUT_JSON, len(new_clubs), "clubs")


if __name__ == "__main__":
    main()
