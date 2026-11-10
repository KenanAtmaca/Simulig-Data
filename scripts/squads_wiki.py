"""First-team squads of every catalog club from Wikipedia (raw wikitext via action=raw).

English Wikipedia club articles keep the squad in a "Current squad" / "First-team squad" section
built from {{Fs start}} / {{Fs player|no=|nat=|pos=|name=}} / {{Fs mid}} / {{Fs end}}
(older pages: {{Football squad player}}). Some articles transclude the list from another page
(a "<Club> squad" template, a "Players of <Club>" or "List of ... players" page); those are
followed. Turkish clubs fall back to Turkish Wikipedia when the English page has no usable list
(same Fs templates or the Turkish variants such as {{Fs oyuncu|no=|ülke=|poz=|isim=}}).

    python3 squads_wiki.py <work-dir> <teams.json> <out squads.json> [--offline] [--version N]

<work-dir> caches every downloaded page (<work-dir>/en/..., <work-dir>/tr/...); with --offline only
the cache is used. The output is written only if every club passes validation (exit code 1 otherwise).

Output: {"version": YYYYMMDDHH, "generatedAt": ISO8601 UTC,
         "teams": {"tr-gs": [{"name": ..., "number": 1 or null, "position": "GK"|"DF"|"MF"|"FW",
                               "note": optional}, ...]}}
Players are ordered GK, DF, MF, FW, then by number (no number last).
"""
import datetime as dt, hashlib, html, json, os, re, sys, time, urllib.parse, urllib.request

UA = "SimuligDataBot/1.0 (data pipeline)"
URL = "https://{lang}.wikipedia.org/w/index.php?title={title}&action=raw"
DELAY = 0.4  # seconds between live requests

# team id -> English Wikipedia article. An optional second value is the Turkish Wikipedia
# article used when the English page has no parsable first-team list.
TITLES = {
    # Süper Lig
    "tr-gs": ("Galatasaray S.K. (football)", "Galatasaray (futbol takımı)"),
    "tr-fb": ("Fenerbahçe S.K. (football)", "Fenerbahçe (futbol takımı)"),
    "tr-bjk": ("Beşiktaş J.K.", "Beşiktaş (futbol takımı)"),
    "tr-ts": ("Trabzonspor", "Trabzonspor"),
    "tr-ibfk": ("İstanbul Başakşehir F.K.", "Başakşehir FK"),
    "tr-sam": ("Samsunspor", "Samsunspor"),
    "tr-goz": ("Göztepe S.K.", "Göztepe (futbol takımı)"),
    "tr-aln": ("Alanyaspor", "Alanyaspor"),
    "tr-kon": ("Konyaspor", "Konyaspor"),
    "tr-kas": ("Kasımpaşa S.K.", "Kasımpaşa SK"),
    "tr-gfk": ("Gaziantep F.K.", "Gaziantep FK"),
    "tr-riz": ("Çaykur Rizespor", "Çaykur Rizespor"),
    "tr-eyp": ("Eyüpspor", "Eyüpspor"),
    "tr-koc": ("Kocaelispor", "Kocaelispor"),
    "tr-gb": ("Gençlerbirliği S.K.", "Gençlerbirliği (futbol takımı)"),
    "tr-amd": ("Amed S.F.K.", "Amed SFK"),
    "tr-cor": ("Çorum FK", "Çorum FK"),
    "tr-erz": ("Erzurumspor F.K.", "Erzurumspor FK"),
    # 1. Lig
    "tr1-bur": ("Bursaspor", "Bursaspor (futbol takımı)"),
    "tr-kay": ("Kayserispor", "Kayserispor"),
    "tr1-igd": ("Iğdır FK", "Iğdır FK"),
    "tr1-mar": ("Mardin 1969 S.K.", "Mardin 1969 SK"),
    "tr1-bat": ("Batman Petrolspor", "Batman Petrolspor"),
    "tr1-kec": ("Ankara Keçiörengücü S.K.", "Ankara Keçiörengücü SK"),
    "tr1-bod": ("Bodrum F.K.", "Bodrum FK"),
    "tr-ant": ("Antalyaspor", "Antalyaspor"),
    "tr-fkg": ("Fatih Karagümrük S.K.", "Fatih Karagümrük SK"),
    "tr1-ero": ("Esenler Erokspor", "Esenler Erokspor"),
    "tr1-mug": ("Muğlaspor", "Muğlaspor"),
    "tr1-umr": ("Ümraniyespor", "Ümraniyespor"),
    "tr1-sar": ("Sarıyer S.K.", "Sarıyer SK"),
    "tr1-van": ("Vanspor FK", "Vanspor FK"),
    "tr1-ban": ("Bandırmaspor", "Bandırmaspor"),
    "tr1-pen": ("Pendikspor", "Pendikspor"),
    "tr1-man": ("Manisa F.K.", "Manisa FK"),
    "tr1-siv": ("Sivasspor", "Sivasspor"),
    "tr1-ist": ("İstanbulspor", "İstanbulspor"),
    "tr1-bol": ("Boluspor", "Boluspor"),
    # Premier League
    "eng-ars": ("Arsenal F.C.",), "eng-avl": ("Aston Villa F.C.",), "eng-bou": ("AFC Bournemouth",),
    "eng-bre": ("Brentford F.C.",), "eng-bha": ("Brighton & Hove Albion F.C.",), "eng-che": ("Chelsea F.C.",),
    "eng-cov": ("Coventry City F.C.",), "eng-cry": ("Crystal Palace F.C.",), "eng-eve": ("Everton F.C.",),
    "eng-ful": ("Fulham F.C.",), "eng-hul": ("Hull City A.F.C.",), "eng-ips": ("Ipswich Town F.C.",),
    "eng-lee": ("Leeds United F.C.",), "eng-liv": ("Liverpool F.C.",), "eng-mci": ("Manchester City F.C.",),
    "eng-mun": ("Manchester United F.C.",), "eng-new": ("Newcastle United F.C.",),
    "eng-nfo": ("Nottingham Forest F.C.",), "eng-sun": ("Sunderland A.F.C.",),
    "eng-tot": ("Tottenham Hotspur F.C.",),
    # La Liga
    "esp-ala": ("Deportivo Alavés",), "esp-ath": ("Athletic Bilbao",), "esp-atm": ("Atlético Madrid",),
    "esp-bar": ("FC Barcelona",), "esp-bet": ("Real Betis",), "esp-cel": ("RC Celta de Vigo",),
    "esp-elc": ("Elche CF",), "esp-esp": ("RCD Espanyol",), "esp-get": ("Getafe CF",),
    "esp-dep": ("Deportivo de La Coruña",), "esp-lev": ("Levante UD",), "esp-mal": ("Málaga CF",),
    "esp-osa": ("CA Osasuna",), "esp-rma": ("Real Madrid CF",), "esp-rac": ("Racing de Santander",),
    "esp-sev": ("Sevilla FC",), "esp-rso": ("Real Sociedad",), "esp-val": ("Valencia CF",),
    "esp-ray": ("Rayo Vallecano",), "esp-vil": ("Villarreal CF",),
    # Serie A
    "ita-ata": ("Atalanta BC",), "ita-bol": ("Bologna FC 1909",), "ita-cag": ("Cagliari Calcio",),
    "ita-com": ("Como 1907",), "ita-fio": ("ACF Fiorentina",), "ita-fro": ("Frosinone Calcio",),
    "ita-gen": ("Genoa CFC",), "ita-int": ("Inter Milan",), "ita-juv": ("Juventus FC",),
    "ita-laz": ("SS Lazio",), "ita-lec": ("US Lecce",), "ita-mil": ("AC Milan",), "ita-mon": ("AC Monza",),
    "ita-nap": ("SSC Napoli",), "ita-par": ("Parma Calcio 1913",), "ita-rom": ("AS Roma",),
    "ita-sas": ("US Sassuolo Calcio",), "ita-tor": ("Torino FC",), "ita-udi": ("Udinese Calcio",),
    "ita-ven": ("Venezia FC",),
    # Bundesliga
    "ger-fca": ("FC Augsburg",), "ger-bay": ("FC Bayern Munich",), "ger-bvb": ("Borussia Dortmund",),
    "ger-sge": ("Eintracht Frankfurt",), "ger-elv": ("SV Elversberg",), "ger-koe": ("1. FC Köln",),
    "ger-scf": ("SC Freiburg",), "ger-hsv": ("Hamburger SV",), "ger-tsg": ("TSG Hoffenheim",),
    "ger-b04": ("Bayer 04 Leverkusen",), "ger-bmg": ("Borussia Mönchengladbach",),
    "ger-m05": ("1. FSV Mainz 05",), "ger-scp": ("SC Paderborn 07",), "ger-rbl": ("RB Leipzig",),
    "ger-s04": ("FC Schalke 04",), "ger-vfb": ("VfB Stuttgart",), "ger-fcu": ("1. FC Union Berlin",),
    "ger-svw": ("SV Werder Bremen",),
    # Ligue 1
    "fra-sco": ("Angers SCO",), "fra-aux": ("AJ Auxerre",), "fra-sb29": ("Stade Brestois 29",),
    "fra-hac": ("Le Havre AC",), "fra-lem": ("Le Mans FC",), "fra-rcl": ("RC Lens",), "fra-los": ("Lille OSC",),
    "fra-fcl": ("FC Lorient",), "fra-ol": ("Olympique Lyonnais",), "fra-om": ("Olympique de Marseille",),
    "fra-asm": ("AS Monaco FC",), "fra-ogcn": ("OGC Nice",), "fra-pfc": ("Paris FC",),
    "fra-psg": ("Paris Saint-Germain FC",), "fra-srfc": ("Stade Rennais FC",),
    "fra-rcsa": ("RC Strasbourg Alsace",), "fra-tfc": ("Toulouse FC",), "fra-est": ("ES Troyes AC",),
    # Eredivisie
    "ned-az": ("AZ Alkmaar",), "ned-aja": ("AFC Ajax",), "ned-cam": ("SC Cambuur",), "ned-ado": ("ADO Den Haag",),
    "ned-exc": ("Excelsior Rotterdam",), "ned-fey": ("Feyenoord",), "ned-for": ("Fortuna Sittard",),
    "ned-gae": ("Go Ahead Eagles",), "ned-gro": ("FC Groningen",), "ned-hee": ("SC Heerenveen",),
    "ned-nec": ("NEC Nijmegen",), "ned-psv": ("PSV Eindhoven",), "ned-spa": ("Sparta Rotterdam",),
    "ned-tel": ("SC Telstar",), "ned-twe": ("FC Twente",), "ned-utr": ("FC Utrecht",),
    "ned-wil": ("Willem II (football club)",), "ned-pec": ("PEC Zwolle",),
    # Primeira Liga
    "por-avi": ("Académico de Viseu F.C.",), "por-alv": ("F.C. Alverca",), "por-aro": ("F.C. Arouca",),
    "por-slb": ("S.L. Benfica",), "por-cpi": ("Casa Pia A.C.",), "por-est": ("G.D. Estoril Praia",),
    "por-ama": ("C.F. Estrela da Amadora",), "por-fam": ("F.C. Famalicão",), "por-gil": ("Gil Vicente F.C.",),
    "por-vsc": ("Vitória S.C.",), "por-mar": ("C.S. Marítimo",), "por-mor": ("Moreirense F.C.",),
    "por-nac": ("C.D. Nacional",), "por-fcp": ("FC Porto",), "por-rio": ("Rio Ave F.C.",),
    "por-scl": ("C.D. Santa Clara",), "por-bra": ("S.C. Braga",), "por-scp": ("Sporting CP",),
}

# Special cases: clubs whose first-team list on Wikipedia is completed by another section
# (B-team players who hold first-team squad numbers). Only numbered players are added.
SUPPLEMENT = {
    "esp-cel": "Reserve team",   # Celta lists only 3 MF in the first team; the B players with dorsals complete it
}

POS_ORDER = ["GK", "DF", "MF", "FW"]
POSITIONS = {
    "GK": "GK", "G": "GK", "GOALKEEPER": "GK", "K": "GK", "KL": "GK", "KALECI": "GK", "KALECİ": "GK", "POR": "GK", "TW": "GK",
    "DF": "DF", "D": "DF", "DEF": "DF", "DEFENDER": "DF", "DEFANS": "DF", "DEFANS OYUNCUSU": "DF", "SB": "DF", "CB": "DF",
    "RB": "DF", "LB": "DF", "WB": "DF", "LWB": "DF", "RWB": "DF", "STOPER": "DF", "BEK": "DF",
    "MF": "MF", "M": "MF", "MID": "MF", "MIDFIELDER": "MF", "OS": "MF", "O": "MF", "ORTA SAHA": "MF", "ORTASAHA": "MF",
    "ORTA SAHA OYUNCUSU": "MF", "DM": "MF", "CM": "MF", "AM": "MF", "LM": "MF", "RM": "MF",
    "FW": "FW", "F": "FW", "FWD": "FW", "FORWARD": "FW", "FV": "FW", "FORVET": "FW", "ST": "FW", "CF": "FW",
    "LW": "FW", "RW": "FW", "W": "FW", "SF": "FW", "KANAT": "FW", "STRIKER": "FW",
}

PLAYER_TPL = re.compile(r"^(fs\s*player|fs\s*player2|football\s*squad\s*player|fs\s*oyuncu|futbol\s*kadrosu\s*oyuncu|"
                        r"futbol\s*kadro\s*oyuncu|fs2\s*player|football\s*squad\s*player\s*2)$", re.I)
HEADING = re.compile(r"^(={2,6})\s*(.*?)\s*\1\s*$", re.M)
# Pseudo-headings inside a section (";Out on loan", bold "Out on loan" lines); they end a list
# only when their text is one of the NOT_FIRST kinds.
PSEUDO = re.compile(r"^(?:;\s*(.+?)|'''\s*(.+?)\s*'''\s*:?)\s*$", re.M)
# Section headings that hold the first-team list (English and Turkish).
SQUAD_HEAD = re.compile(r"(current\s+squad|first[\s-]*team(\s+squad)?|^squad$|^players$|^current\s+players|"
                        r"senior\s+squad|^kadro$|güncel\s+kadro|mevcut\s+kadro|a\s+takım|^oyuncular$|"
                        r"profesyonel\s+kadro|şu\s+anki\s+kadro|^squad\s+\d{4}|kadro\s*\(\d{4})", re.I)
# Headings that never hold the first team.
NOT_FIRST = re.compile(r"loan|kiral|reserve|youth|academy|women|ladies|u-?\s?\d\d|under-?\s?\d\d|b\s+team|"
                       r"\bii\b|retired|former|notable|famous|record|captain|staff|management|technical|"
                       r"altyapı|kadın|genç|rezerv|emekli|eski|unutulmaz|teknik|yönetim|history|tarihçe|"
                       r"non-playing|player of|hall of fame|statistics|futsal|basketball|honours|primavera|"
                       r"next\s*gen|development|second\s+team|\bb\b|2\.\s*takım", re.I)


class SquadError(Exception):
    pass


# ------------------------------------------------------------------ fetching

class Wiki:
    def __init__(self, cache, offline=False):
        self.cache, self.offline, self.requests = cache, offline, 0

    def _path(self, lang, title):
        key = hashlib.sha1(title.encode("utf-8")).hexdigest()[:16]
        safe = re.sub(r"[^\w.-]+", "_", title)[:60]
        return os.path.join(self.cache, lang, f"{safe}-{key}.txt")

    def raw(self, lang, title):
        """Raw wikitext or None if the page does not exist. Cached."""
        p = self._path(lang, title)
        if os.path.exists(p):
            t = open(p, encoding="utf-8").read()
            return None if t == "\0missing" else t
        if self.offline: raise SquadError(f"offline and not cached: {lang}:{title}")
        url = URL.format(lang=lang, title=urllib.parse.quote(title.replace(" ", "_"), safe=":_()'!,"))
        text, last = None, None
        for attempt in range(3):
            try:
                time.sleep(DELAY)
                self.requests += 1
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=60) as r:
                    text = r.read().decode("utf-8")
                break
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    text = "\0missing"
                    break
                last = e
            except Exception as e:  # network hiccup: retry
                last = e
            time.sleep(3 * (attempt + 1))
        if text is None: raise SquadError(f"download failed: {lang}:{title}: {last}")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "w", encoding="utf-8").write(text)
        return None if text == "\0missing" else text

    def page(self, lang, title):
        """Follow #REDIRECT (up to 4 hops). Returns (final title, text) or (title, None)."""
        for _ in range(5):
            text = self.raw(lang, title)
            if text is None: return title, None
            m = re.match(r"\s*#(?:REDIRECT|YÖNLENDİRME|YÖNLENDİR)\s*\[\[([^\]|#]+)", text, re.I)
            if not m: return title, text
            title = m.group(1).strip()
        raise SquadError(f"redirect loop at {lang}:{title}")


# ------------------------------------------------------------------ wikitext helpers

def templates(text):
    """Yield (start, end, body) of every top-level {{...}} in text (balanced braces)."""
    i, n = 0, len(text)
    while True:
        i = text.find("{{", i)
        if i < 0: return
        depth, j = 0, i
        while j < n:
            if text.startswith("{{", j): depth += 1; j += 2
            elif text.startswith("}}", j):
                depth -= 1; j += 2
                if depth == 0: break
            else: j += 1
        if depth != 0: return
        yield i, j, text[i + 2:j - 2]
        i = j


def split_params(body):
    """Split a template body on top-level '|' (ignoring pipes inside [[ ]] and {{ }})."""
    parts, depth_t, depth_l, cur, i = [], 0, 0, [], 0
    while i < len(body):
        two = body[i:i + 2]
        if two == "{{": depth_t += 1; cur.append(two); i += 2; continue
        if two == "}}": depth_t -= 1; cur.append(two); i += 2; continue
        if two == "[[": depth_l += 1; cur.append(two); i += 2; continue
        if two == "]]": depth_l -= 1; cur.append(two); i += 2; continue
        c = body[i]
        if c == "|" and depth_t == 0 and depth_l == 0:
            parts.append("".join(cur)); cur = []
        else:
            cur.append(c)
        i += 1
    parts.append("".join(cur))
    name = parts[0].strip()
    named, pos = {}, []
    for p in parts[1:]:
        m = re.match(r"\s*([^=\[\]{}]+?)\s*=(.*)$", p, re.S)
        if m: named[m.group(1).strip().lower()] = m.group(2).strip()
        else: pos.append(p.strip())
    return name, named, pos


def strip_noise(s):
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    s = re.sub(r"<ref[^>/]*/>", "", s, flags=re.I)
    s = re.sub(r"<ref[^>]*>.*?</ref>", "", s, flags=re.I | re.S)
    return s


def clean(s):
    """Wikitext fragment -> plain text."""
    s = strip_noise(s)
    # templates: keep the readable ones, drop the rest (footnotes, flags, icons)
    out, last = [], 0
    for a, b, body in templates(s):
        out.append(s[last:a]); last = b
        name, named, pos = split_params(body)
        ln = name.lower().strip()
        if ln in ("sortname", "sort name", "sıralaadı", "sirala", "sort"):
            if ln == "sort" and len(pos) >= 2: out.append(clean(pos[1]))
            elif len(pos) >= 2: out.append(clean(pos[0]) + " " + clean(pos[1]))
            elif pos: out.append(clean(pos[0]))
        elif ln in ("nowrap", "nobr", "lang", "noitalic", "nobold", "small", "ill", "interlanguage link", "illm",
                    "lang-tr", "transl", "nihongo", "proper name", "korean", "abbr") and pos:
            out.append(clean(pos[1] if ln in ("lang", "transl", "korean") and len(pos) > 1 else pos[0]))
        # everything else (efn, refn, flagicon, captain markers, ...) is dropped
    out.append(s[last:])
    s = "".join(out)
    s = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", s)   # [[A|B]] -> B, [[A]] -> A
    s = re.sub(r"\[https?://\S+\s*([^\]]*)\]", r"\1", s)        # external links
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("'''", "").replace("''", "")
    s = html.unescape(s).replace(" ", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


NOTE_RE = re.compile(r"\s*\(([^()]*)\)\s*$")


def clean_name(raw):
    name, notes = clean(raw), []
    while True:
        m = NOTE_RE.search(name)
        if not m: break
        txt = m.group(1).strip()
        low = txt.lower()
        if re.search(r"captain|kaptan|loan|kiral|vice|c\b", low) or low in ("c", "vc", "k"):
            notes.append(txt)
        name = name[:m.start()].strip()
    name = re.sub(r"[\s*†‡#^]+$", "", name).strip()   # footnote markers
    return name, notes


def position(raw):
    p = clean(raw).upper().strip(" .")
    if p in POSITIONS: return POSITIONS[p]
    p2 = p.split("/")[0].split(",")[0].strip()
    if p2 in POSITIONS: return POSITIONS[p2]
    return None


def number(raw):
    m = re.match(r"\s*(\d{1,2})\b", clean(raw))
    return int(m.group(1)) if m else None


def _braced(text, i):
    """Content of the balanced {...} starting at text[i] == '{', and the index after it."""
    depth, j = 0, i
    while j < len(text):
        if text[j] == "{": depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0: return text[i + 1:j], j + 1
        j += 1
    return None, len(text)


def _fields(s):
    """'ad=[[A|B]],pozisyon=DF,ülke=TUR' -> dict (commas inside [[ ]] / {{ }} are kept)."""
    out, depth, cur = {}, 0, ""
    for k, c in enumerate(s + ","):
        if s[k:k + 2] in ("[[", "{{"): depth += 1
        elif s[k:k + 2] in ("]]", "}}"): depth -= 1
        if c == "," and depth <= 0:
            if "=" in cur:
                key, val = cur.split("=", 1); out[key.strip().lower()] = val.strip()
            cur = ""
        else:
            cur += c
    return out


TR_SLOT = re.compile(r"\|\s*numara_(\d+|bilinmeyen)\s*=\s*(?=\{)")


def module_players(block):
    """Turkish Wikipedia squad module: {{#invoke:Futbol takımı kadrosu|kadro|numara_1={ad=..,pozisyon=..,ülke=..}
    |numara_bilinmeyen={ {ad=..}, ... }}} -> [(number or None, fields)]."""
    if not re.search(r"#invoke:\s*Futbol takımı kadrosu", block, re.I): return []
    res = []
    for m in TR_SLOT.finditer(block):
        body, _ = _braced(block, m.end())
        if body is None: continue
        if m.group(1) == "bilinmeyen":
            k = 0
            while True:
                k = body.find("{", k)
                if k < 0: break
                inner, k = _braced(body, k)
                if inner and "{" not in inner.replace("{{", ""): res.append((None, _fields(inner)))
        else:
            res.append((int(m.group(1)), _fields(body)))
    return res


def make_player(nm_raw, pos_raw, no, other):
    nm, notes = clean_name(nm_raw)
    ps = position(pos_raw)
    other = clean(other)
    if other:
        o = re.sub(r"^\(|\)$", "", other).strip()
        if o and len(o) <= 60 and not re.search(r"[\[\]{}|=]", o): notes.insert(0, o)
    if not nm or ps is None: return None
    p = {"name": nm, "number": no, "position": ps}
    if notes: p["note"] = "; ".join(dict.fromkeys(notes))
    return p


def players_in(block):
    """Every Fs-style player template (or Turkish squad-module entry) in a block of wikitext."""
    out, bad = [], []
    for no, f in module_players(strip_noise(block)):
        loan = f.get("kiralık", "")
        p = make_player(f.get("ad", f.get("isim", "")), f.get("pozisyon", f.get("poz", "")), no,
                        (f"kiralık: {loan}" if loan else ""))
        if p: out.append(p)
        else: bad.append((f.get("ad"), f.get("pozisyon")))
    for _, _, body in templates(strip_noise(block)):
        name, named, pos = split_params(body)
        if not PLAYER_TPL.match(re.sub(r"\s+", " ", name.replace("_", " ")).strip()): continue
        g = lambda *ks: next((named[k] for k in ks if named.get(k)), "")
        p = make_player(g("name", "isim", "ad", "oyuncu", "player"), g("pos", "poz", "mevki", "position"),
                        number(g("no", "num", "number", "numara")), g("other", "diğer", "not", "note"))
        if p: out.append(p)
        else: bad.append((g("name", "isim"), g("pos", "poz")))
    return out, bad


def sections(text):
    """[(level, heading, body)] for every heading; body runs to the next heading of any level."""
    hs = [(h.start(), h.end(), len(h.group(1)), h.group(2)) for h in HEADING.finditer(text)]
    hs += [(m.start(), m.end(), 7, m.group(1) or m.group(2)) for m in PSEUDO.finditer(text)
           if NOT_FIRST.search(clean(m.group(1) or m.group(2)))]
    hs.sort()
    res = []
    for k, (a, b, lvl, head) in enumerate(hs):
        end = hs[k + 1][0] if k + 1 < len(hs) else len(text)
        res.append((lvl, clean(head), text[b:end], a))
    return res


def transclusions(block):
    """Page titles transcluded or pointed to (main/see also) in a block, in order."""
    out = []
    for _, _, body in templates(strip_noise(block)):
        name, named, pos = split_params(body)
        ln = name.lower().strip()
        if ln in ("main", "main article", "see also", "further", "ana", "ayrıca bakınız", "ana madde"):
            out += [p for p in pos if p]
        elif ln.startswith((":", "template:", "şablon:")):
            out.append(name.lstrip(":"))
        elif re.search(r"squad|kadro|players", ln) and not re.match(r"fs\b|football squad|futbol kadro", ln):
            out.append("Template:" + name if ":" not in name else name)
    return out


def best_block(text):
    """Pick the first-team list in an article: (players, how) or (None, reason)."""
    secs = sections(text)
    # 1. headings that look like the first-team section and contain player templates
    for lvl, head, body, _ in secs:
        if SQUAD_HEAD.search(head) and not NOT_FIRST.search(head):
            ps, _ = players_in(body)
            if len(ps) >= 11: return ps, f"section '{head}'", []
    # 2. headings that look right but point elsewhere
    links = []
    for lvl, head, body, _ in secs:
        if SQUAD_HEAD.search(head) and not NOT_FIRST.search(head):
            links += transclusions(body)
    # 3. no heading matched: the first Fs list in the article that is not under an excluded heading
    if not links:
        for lvl, head, body, _ in secs:
            if NOT_FIRST.search(head): continue
            ps, _ = players_in(body)
            if len(ps) >= 15: return ps, f"first list (section '{head}')", []
    return None, "no squad section", links


def supplement(wiki, lang, title, head):
    _, text = wiki.page(lang, title)
    for lvl, h, body, _ in sections(text or ""):
        if h.lower() == head.lower():
            return [p for p in players_in(body)[0] if p["number"] is not None]
    raise SquadError(f"{lang}:{title}: no section '{head}' to supplement from")


def squad_from_page(wiki, lang, title, depth=0):
    """(players, description) from a page, following transcluded squad pages once."""
    final, text = wiki.page(lang, title)
    if text is None: return None, f"{lang}:{title} missing"
    ps, how, links = best_block(text)
    if ps: return ps, f"{lang}:{final} {how}"
    if depth == 0:
        # squad templates first, then other pages ("List of ... players" pages hold all-time lists)
        links = sorted(dict.fromkeys(links), key=lambda t: 0 if re.match(r"(template|şablon):", t, re.I) else 1)
        for link in links:
            ps, how2 = squad_from_page(wiki, lang, link, depth + 1)
            if ps: return ps, f"{lang}:{final} -> {how2}"
        # a whole page that is only the list (a squad template): take its players directly
    elif text:
        ps, _ = players_in(re.split(r"<noinclude>", text)[0])
        if len(ps) >= 11: return ps, f"{lang}:{final} (whole page)"
    return None, f"{lang}:{final}: {how}"


# ------------------------------------------------------------------ validation and output

def order(players):
    return sorted(players, key=lambda p: (POS_ORDER.index(p["position"]), p["number"] if p["number"] is not None else 999))


def check(tid, ps):
    errs = []
    if not 18 <= len(ps) <= 40: errs.append(f"{len(ps)} players (18..40)")
    cnt = {k: sum(1 for p in ps if p["position"] == k) for k in POS_ORDER}
    for k, lo in (("GK", 2), ("DF", 5), ("MF", 5), ("FW", 2)):
        if cnt[k] < lo: errs.append(f"{cnt[k]} {k} (min {lo})")
    names = [p["name"] for p in ps]
    if any(not n.strip() for n in names): errs.append("empty name")
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup: errs.append(f"duplicate names {dup}")
    for p in ps:
        if p["number"] is not None and not 1 <= p["number"] <= 99: errs.append(f"{p['name']}: number {p['number']}")
        if any(x in p["name"] for x in ("{{", "[[", "|", "=", "}}", "]]")): errs.append(f"markup in name {p['name']!r}")
        if p["position"] not in POS_ORDER: errs.append(f"{p['name']}: position {p['position']}")
    return errs


def validate(doc, club_ids):
    """Validation errors for a whole squads document (also used by update_all.py)."""
    errs = []
    teams = doc.get("teams", {})
    missing = sorted(set(club_ids) - set(teams))
    extra = sorted(set(teams) - set(club_ids))
    if missing: errs.append(f"missing clubs: {missing}")
    if extra: errs.append(f"unknown clubs: {extra}")
    for tid in sorted(set(teams) & set(club_ids)):
        errs += [f"{tid}: {e}" for e in check(tid, teams[tid])]
    if not isinstance(doc.get("version"), int): errs.append("version must be an int")
    try:
        dt.datetime.strptime(doc.get("generatedAt", ""), "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        errs.append(f"generatedAt not ISO8601 UTC: {doc.get('generatedAt')}")
    return errs


def build(wiki, clubs):
    """clubs: [(id, competition)]. Returns (teams, report, errors)."""
    teams, report, errs = {}, [], []
    for tid, comp in clubs:
        if tid not in TITLES:
            errs.append(f"{tid}: no Wikipedia title in TITLES"); continue
        en, tr = TITLES[tid][0], (TITLES[tid][1] if len(TITLES[tid]) > 1 else None)
        tried = []
        ps, how = squad_from_page(wiki, "en", en)
        if ps and tid in SUPPLEMENT:
            extra = [p for p in supplement(wiki, "en", en, SUPPLEMENT[tid]) if p["name"] not in {x["name"] for x in ps}]
            ps = ps + extra
            how += f" + {len(extra)} numbered players from '{SUPPLEMENT[tid]}' [special case]"
        problems = check(tid, order(ps)) if ps else ["no list"]
        if problems and tr:
            tried.append(f"en failed ({how}; {', '.join(problems)})")
            ps2, how2 = squad_from_page(wiki, "tr", tr)
            p2 = check(tid, order(ps2)) if ps2 else ["no list"]
            if not p2:
                ps, how, problems = ps2, how2 + " [Turkish fallback]", []
            else:
                tried.append(f"tr failed ({how2}; {', '.join(p2)})")
        if problems:
            errs.append(f"{tid}: {'; '.join(tried) or how + '; ' + ', '.join(problems)}")
            continue
        teams[tid] = order(ps)
        report.append((tid, comp, len(ps), how))
    return teams, report, errs


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 3: raise SystemExit(__doc__)
    work, teams_path, out = args
    version = None
    if "--version" in sys.argv:
        version = int(sys.argv[sys.argv.index("--version") + 1]); args = [a for a in args if a != str(version)]
    cat = json.load(open(teams_path, encoding="utf-8"))
    clubs = [(t["id"], t["competition"]) for t in cat["teams"] if t["kind"] == "club"]
    wiki = Wiki(work, offline="--offline" in sys.argv)
    teams, report, errs = build(wiki, clubs)
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    doc = {"version": version or int(now.strftime("%Y%m%d%H")), "generatedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
           "teams": {tid: teams[tid] for tid, _ in clubs if tid in teams}}
    if not errs: errs = validate(doc, [c for c, _ in clubs])
    print(f"squads: {len(teams)}/{len(clubs)} clubs, {wiki.requests} requests")
    comps = {}
    for tid, comp, n, how in report:
        comps.setdefault(comp, []).append(n)
    for comp, ns in comps.items():
        print(f"  {comp:15s} {len(ns):2d} clubs, {sum(ns)} players, avg {sum(ns) / len(ns):.1f}, min {min(ns)}, max {max(ns)}")
    for tid, comp, n, how in report:
        if "->" in how or "[" in how or "first list" in how or "whole page" in how:
            print(f"  special {tid}: {how}")
    if errs:
        for e in errs: print("  INVALID:", e)
        print(f"FAILED: {len(errs)} errors; nothing written")
        return 1
    tmp = out + ".tmp"
    json.dump(doc, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, out)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
