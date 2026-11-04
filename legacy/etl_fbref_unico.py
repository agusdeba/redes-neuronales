#!/usr/bin/env python3
"""ETL unico FBref.

Reconstruye TODAS las tablas de estadisticas de jugadores de FBref en un unico
esquema canonico (30 columnas), normalizando los formatos de entrada (raw 2-lineas,
salidas reset_index sin aplanar, ya planas), decodificando temporadas a formato
legible y aplicando fuzzy matching (rapidfuzz) para consolidar jugadores.

Uso:
    python etl_fbref_unico.py            # regenera todas las ligas
    python etl_fbref_unico.py --quarantine   # mueve los archivos obsoletos a _obsoletos/
"""

import argparse
import csv
import os
import re
import sys
import unicodedata

import pandas as pd

from rapidfuzz import fuzz

ROOT = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(ROOT, "csv")
OBSOLETOS = os.path.join(ROOT, "_obsoletos")
FUZZY_MIN = 92.0

BASE_COLS = ["league", "season", "team", "player", "nation", "pos", "age", "born",
             "mp", "starts", "minutes", "nineties", "goals", "assists", "g_plus_a",
             "g_minus_pk", "pk", "pkatt", "crdy", "crdr", "goals_90", "assists_90",
             "g_plus_a_90", "g_minus_pk_90", "g_plus_a_minus_pk_90"]
ENRICH_COLS = ["player_id", "match_score", "debut_season", "is_debut"]
OUT_COLS = BASE_COLS + ENRICH_COLS

NUM_COLS = ["age", "born", "mp", "starts", "minutes", "nineties", "goals", "assists",
            "g_plus_a", "g_minus_pk", "pk", "pkatt", "crdy", "crdr", "goals_90",
            "assists_90", "g_plus_a_90", "g_minus_pk_90", "g_plus_a_minus_pk_90"]

# Mapeo de columnas de los raw por temporada (header 'Rk,Player,...,G+A-PK')
COLMAP = {"Player": "player", "Nation": "nation", "Pos": "pos", "Squad": "team",
          "Age": "age", "Born": "born", "MP": "mp", "Starts": "starts", "Min": "minutes",
          "90s": "nineties", "Gls": "goals", "Ast": "assists", "G+A": "g_plus_a",
          "G-PK": "g_minus_pk", "PK": "pk", "PKatt": "pkatt", "CrdY": "crdy", "CrdR": "crdr"}
PER90_MAP = {"Gls": "goals_90", "Ast": "assists_90", "G+A": "g_plus_a_90",
             "G-PK": "g_minus_pk_90", "G+A-PK": "g_plus_a_minus_pk_90"}
DUP = {"Gls", "Ast", "G+A", "G-PK"}
DROP_COLS = {"Rk", "Matches", "-9999", "Unnamed", "club", "Matches"}

# (folder, slug, season_type, mode, input, output)
BIG5_TEAM_OVERRIDES = {
    "1860munich": "GER-Bundesliga", "arminia": "GER-Bundesliga",
    "bayernmunich": "GER-Bundesliga", "dortmund": "GER-Bundesliga",
    "frankfurt": "GER-Bundesliga", "freiburg": "GER-Bundesliga",
    "hamburgersv": "GER-Bundesliga", "hansarostock": "GER-Bundesliga",
    "herthabsc": "GER-Bundesliga", "kaiserslautern": "GER-Bundesliga",
    "leverkusen": "GER-Bundesliga", "msvduisburg": "GER-Bundesliga",
    "schalke04": "GER-Bundesliga", "stuttgart": "GER-Bundesliga",
    "ulm": "GER-Bundesliga", "unterhaching": "GER-Bundesliga",
    "werderbremen": "GER-Bundesliga", "wolfsburg": "GER-Bundesliga",
    "auxerre": "FRA-Ligue 1", "bastia": "FRA-Ligue 1",
    "bordeaux": "FRA-Ligue 1", "lehavre": "FRA-Ligue 1",
    "lens": "FRA-Ligue 1", "lyon": "FRA-Ligue 1",
    "marseille": "FRA-Ligue 1", "metz": "FRA-Ligue 1",
    "monaco": "FRA-Ligue 1", "montpellier": "FRA-Ligue 1",
    "nancy": "FRA-Ligue 1", "nantes": "FRA-Ligue 1",
    "parissg": "FRA-Ligue 1", "rennes": "FRA-Ligue 1",
    "saintetienne": "FRA-Ligue 1", "sedan": "FRA-Ligue 1",
    "strasbourg": "FRA-Ligue 1", "troyes": "FRA-Ligue 1",
}


LEAGUES = [
    dict(folder="Big5EuropeanLeague", slug="Big5EuropeanLeague", season_type="multi",
         mode="raw", source="fbref_big5_*.csv",
         out_name="Big5EuropeanLeague1995_2026.csv",
         league_aux=[("raw_GER-Bundesliga_1995_2026.csv", "GER-Bundesliga"),
                     ("raw_FRA-Ligue 1_1995_2001.csv", "FRA-Ligue 1")],
         team_overrides=BIG5_TEAM_OVERRIDES),
    dict(folder="portugal", slug="portugal", season_type="multi", mode="flat",
         source="portugal_2000_2026.csv"),
    dict(folder="world_cup", slug="world_cup", season_type="single", mode="flat",
         source="world_cup_1994_2026.csv"),
    dict(folder="wcq_conmebol", slug="wcq_conmebol", season_type="single", mode="raw",
         source="fbref_wcq_conmebol_*.csv", league_label="WCQ-CONMEBOL"),
    dict(folder="wcq_uefa", slug="wcq_uefa", season_type="single", mode="raw",
         source="fbref_wcq_uefa_*.csv", league_label="WCQ-UEFA"),
    dict(folder="ecuador", slug="ecuador", season_type="single", mode="flat",
         source="ecuador_2014_2025.csv"),
    dict(folder="colombia", slug="colombia", season_type="single", mode="flat",
         source="colombia_2015_2025.csv"),
    dict(folder="argentina", slug="argentina", season_type="single", mode="flat",
         source="argentina_2014_2025.csv"),
    dict(folder="brasil", slug="brasil", season_type="single", mode="flat",
         source="brasil_2014_2025.csv"),
    dict(folder="uruguay", slug="uruguay", season_type="single", mode="flat",
         source="uruguay_2014_2025.csv"),
    dict(folder="champions", slug="champions", season_type="multi", mode="raw",
         source="fbref_champions_*.csv", league_label="INT-Champions League"),
    dict(folder="europa_league", slug="europa_league", season_type="multi", mode="raw",
         source="fbref_europa_*.csv", league_label="INT-Europa League"),
    dict(folder="friendlies", slug="friendlies", season_type="single", mode="raw",
         source="fbref_friendlies_*.csv", league_label="INT-FIFA Friendlies"),
    dict(folder="libertadores", slug="libertadores", season_type="single", mode="raw",
         source="fbref_libertadores_*.csv", league_label="INT-Libertadores"),
    dict(folder="sudamericana", slug="sudamericana", season_type="single", mode="raw",
         source="fbref_sudamericana_*.csv", league_label="INT-Sudamericana"),
    dict(folder="copa_america", slug="copa_america", season_type="single", mode="flat",
         source="copa_america_2015_2024.csv", league_label="COPA-AMERICA"),
]

BASELINE = {  # filas esperadas (para el reporte)
    "Big5EuropeanLeague": 82843, "portugal": 13264, "world_cup": 5708,
    "wcq_conmebol": 1668, "wcq_uefa": 9673, "ecuador": 5674, "colombia": 8498,
    "argentina": 10213, "brasil": 8887, "uruguay": 6281, "champions": 20759, "europa_league": 41657,
    "friendlies": 44735, "libertadores": 9167, "sudamericana": 13501,
    "copa_america": 1320,
}

OBSOLETAS = [
    r"C:\Users\Usuario\Desktop\DATA_SETS\FUZZY MATCHING\estadisticas_elite_1995_2005.csv",
    r"C:\Users\Usuario\Desktop\DATA_SETS\FUZZY MATCHING\estadisticas_elite_2005_2015.csv",
    r"C:\Users\Usuario\Desktop\DATA_SETS\FUZZY MATCHING\estadisticas_elite_2014_2026.csv",
    r"C:\Users\Usuario\Desktop\DATA_SETS\FUZZY MATCHING\estadisticas_portugal_2000_2026.csv",
    r"C:\Users\Usuario\Desktop\DATA_SETS\FUZZY MATCHING\estadisticas_argentina_2014_2025.csv",
    r"C:\Users\Usuario\Desktop\DATA_SETS\FUZZY MATCHING\estadisticas_brasil_2014_2025.csv",
    r"C:\Users\Usuario\Desktop\DATA_SETS\downloaded_files\estadisticas_elite_2015_2026.csv",
    r"C:\Users\Usuario\Desktop\DATA_SETS\downloaded_files\estadisticas_etapa_2005_2015.csv",
    r"C:\Users\Usuario\Desktop\DATA_SETS\downloaded_files\estadisticas_etapa_2015_2026.csv",
    r"C:\Users\Usuario\Desktop\fbref\csv\champions\estadisticas_championsleague_1995-2026.csv",
    r"C:\Users\Usuario\Desktop\fbref\csv\europa_league\estadisticas_europaleague_1995-2026.csv",
    r"C:\Users\Usuario\Desktop\fbref\csv\friendlies\estadisticas_friendlies_2014-2025.csv",
    r"C:\Users\Usuario\Desktop\fbref\csv\libertadores\estadisticas_libertadores_2014-2025.csv",
    r"C:\Users\Usuario\Desktop\fbref\csv\sudamericana\estadisticas_sudamericana_2014-2025.csv",
]


# --------------------------------------------------------------------------- helpers

def norm(s):
    if not isinstance(s, str) or not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return "".join(c.lower() for c in s if c.isalnum())


def season_end(label):
    nums = [int(p) for p in re.split(r"-|/", str(label)) if p.strip().isdigit()]
    return nums[-1] if nums else 0


def season_start(label):
    nums = [int(p) for p in re.split(r"-|/", str(label)) if p.strip().isdigit()]
    return nums[0] if nums else 0


def decode_season(label, season_type):
    s = str(label).strip()
    if "/" in s or "-" in s:
        return s
    if not (s.isdigit() and len(s) >= 4):
        return s
    if s.startswith("19") or s.startswith("20"):
        y = int(s[:4])
        if y > 1000:
            if season_type == "multi" and len(s) == 4 and y <= 2500:
                pass  # puede ser codigo de 2 mitades (p.ej. 2021 = 20/21)
            else:
                return s
    code = s.zfill(4)
    h1, h2 = int(code[:2]), int(code[2:])
    start = 2000 + h1 if h1 <= 50 else 1900 + h1
    return "%d-%d" % (start, start + 1)


def clean_nation(v):
    if not isinstance(v, str):
        return ""
    v = v.strip()
    if not v:
        return ""
    return v.split()[0]


def col_map_for_header(header):
    cols, counts = {}, {}
    for j, name in enumerate(header):
        n = name.strip()
        if not n or n in DROP_COLS:
            continue
        if n in DUP:
            k = counts.get(n, 0)
            counts[n] = k + 1
            cols[j] = COLMAP[n] if k == 0 else PER90_MAP[n]
        elif n in PER90_MAP:
            cols[j] = PER90_MAP[n]
        elif n in COLMAP:
            cols[j] = COLMAP[n]
    return cols


# --------------------------------------------------------------------------- loaders

def load_raw_file(path):
    """Parsea un raw por temporada (2 lineas de header, filas-cabecera repetidas)."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.reader(fh))
    hidx = None
    for i, row in enumerate(rows):
        if row and row[0].strip() == "Rk":
            hidx = i
            break
    if hidx is None:
        return None
    cmap = col_map_for_header(rows[hidx])
    out = []
    for row in rows[hidx + 1:]:
        if not row or not row[0].strip():
            continue
        if row[0].strip() == "Rk":
            continue
        d = {}
        ok = True
        for j, canon in cmap.items():
            if j >= len(row):
                continue
            if canon == "player" and not row[j].strip():
                ok = False
                break
            d[canon] = row[j].strip()
        if not ok or "player" not in d:
            continue
        d["nation"] = clean_nation(d.get("nation", "")) if d.get("nation") else ""
        out.append(d)
    return pd.DataFrame(out)


def load_flat_file(path, season_type):
    df = pd.read_csv(path, dtype=str)
    df = df.rename(columns=str.strip)
    for c in BASE_COLS:
        if c not in df.columns:
            df[c] = ""
    df = df[BASE_COLS]
    df["season"] = df["season"].map(lambda s: decode_season(s, season_type))
    df["nation"] = df["nation"].map(clean_nation).fillna("")
    return df


def season_from_filename(name, pattern, season_type):
    base = os.path.basename(name).replace(".csv", "")
    m = re.search(r"(\d{4})-(\d{4})", base)
    if m:
        return "%s-%s" % (m.group(1), m.group(2))
    m = re.search(r"(\d{4})$", base)
    if m:
        return decode_season(m.group(1), "multi") if season_type == "multi" else m.group(1)
    return base


def load_per_season(path, season_type):
    """Intenta raw 2-lineas; si no hay header 'Rk', carga como flat lowercase."""
    df = load_raw_file(path)
    if df is not None:
        return df
    df = pd.read_csv(path, dtype=str).rename(columns=str.strip)
    for c in BASE_COLS:
        if c not in df.columns:
            df[c] = ""
    return df[BASE_COLS]


def fill_leagues(df, folder, aux, overrides=None):
    """Completa filas sin league en el combinado Big5 (GER y FRA pre-0203 no etiquetadas)."""
    overrides = overrides or {}
    aux_map = {}
    for name, league in aux:
        path = os.path.join(CSV, folder, name)
        if not os.path.exists(path):
            continue
        teams = pd.read_csv(path, dtype=str, usecols=["team"])["team"].dropna().astype(str)
        for tb in teams:
            aux_map.setdefault(norm(tb), set()).add(league)
    lab = df[df["league"].notna() & (df["league"].astype(str).str.strip() != "")]
    team_map = {}
    for tb, lg in zip(lab["team"], lab["league"]):
        team_map.setdefault(norm(tb), set()).add(str(lg).strip())

    def assign(team):
        n = norm(team)
        if n in overrides:
            return overrides[n]
        for mp in (team_map, aux_map):
            if n in mp:
                opts = mp[n]
                if len(opts) == 1:
                    return next(iter(opts))
        return None

    mask = df["league"].isna() | (df["league"].astype(str).str.strip() == "")
    df.loc[mask, "league"] = df.loc[mask, "team"].map(assign)
    left = (df["league"].isna() | (df["league"].astype(str).str.strip() == "")).sum()
    if left:
        print("  [!] filas sin league tras fix:", left)
        print(df[df["league"].isna() | (df["league"].astype(str).str.strip() == "")]
              ["team"].value_counts().head(20))
    return df


def load_league(cfg):
    folder = os.path.join(CSV, cfg["folder"])
    frames = []
    if cfg["mode"] == "flat":
        frames.append(load_flat_file(os.path.join(folder, cfg["source"]), cfg["season_type"]))
    else:
        import glob
        for f in sorted(glob.glob(os.path.join(folder, cfg["source"]))):
            df = load_per_season(f, cfg["season_type"])
            df["season"] = decode_season(season_from_filename(f, cfg["source"], cfg["season_type"]),
                                         cfg["season_type"])
            frames.append(df)
    if not frames:
        raise RuntimeError("sin datos para " + cfg["folder"])
    df = pd.concat(frames, ignore_index=True)
    if cfg.get("league_label"):
        df["league"] = cfg["league_label"]
    if cfg.get("league_aux"):
        df = fill_leagues(df, cfg["folder"], cfg["league_aux"], cfg.get("team_overrides"))
    for c in NUM_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["born"] = df["born"].map(lambda v: v if pd.isna(v) else int(v) if float(v) == int(float(v)) else v)
    return df


# --------------------------------------------------------------------------- fuzzy

class Matcher:
    def __init__(self):
        self.groups = []
        self.buckets = {}

    def _key(self, born, first):
        if born is None:
            return (0, first)
        try:
            b = int(born)
        except (ValueError, TypeError):
            return (0, first)
        return (b, first)

    def add(self, norm_name, born, nation):
        if not norm_name:
            return None, 0.0
        key = self._key(born, norm_name[:1])
        bk = self.buckets.setdefault(key, {"map": {}, "reps": []})
        if norm_name in bk["map"]:
            gid = bk["map"][norm_name]
            if nation:
                self.groups[gid]["nations"].add(nation)
            return gid, 100.0
        best_g, best_score = None, 0.0
        for gid, rep in bk["reps"]:
            g = self.groups[gid]
            if nation and g["nations"] and nation not in g["nations"]:
                continue
            s = float(fuzz.WRatio(norm_name, rep))
            a, b2 = len(norm_name), len(rep)
            if (norm_name in rep or rep in norm_name) and min(a, b2) / max(a, b2) >= 0.6:
                s = max(s, min(100.0, s + 15.0))
            if s >= FUZZY_MIN and s > best_score:
                best_g, best_score = gid, s
        if best_g is not None:
            g = self.groups[best_g]
            if not g["nations"] or not nation or nation in g["nations"]:
                bk["map"][norm_name] = best_g
                if nation:
                    g["nations"].add(nation)
                return best_g, best_score
        gid = len(self.groups)
        self.groups.append({"nations": {nation} if nation else set()})
        bk["map"][norm_name] = gid
        bk["reps"].append((gid, norm_name))
        return gid, 100.0

    @staticmethod
    def canonical(raws):
        freq = {}
        for r in raws:
            freq[r] = freq.get(r, 0) + 1
        return max(freq, key=lambda k: (freq[k], -len(k)))


def enrich(df):
    """player_id / match_score / debut_season / is_debut por liga."""
    df = df.copy()
    df["_raw"] = df["player"]
    df["_norm"] = df["player"].map(norm)
    df["_end"] = df["season"].map(season_end)
    frames = []
    for league, sub in df.groupby("league", sort=False):
        matcher = Matcher()
        ids, scores = [], []
        for n, born, nat in zip(sub["_norm"], sub["born"], sub["nation"]):
            gid, sc = matcher.add(n, born, nat) if n else (None, 0.0)
            ids.append(gid)
            scores.append(sc)
        sub = sub.copy()
        sub["player_id"] = ids
        sub["match_score"] = scores
        sub = sub[sub["player_id"].notna()]
        if sub.empty:
            continue
        rows = []
        for gid in sorted(sub["player_id"].astype(int).unique()):
            g = sub[sub["player_id"] == gid]
            played = g[g["mp"] > 0]
            if played.empty:
                continue
            first_end = played["_end"].min()
            debut = played[played["_end"] == first_end].iloc[0]["season"]
            player = Matcher.canonical(g["_raw"].tolist())
            nation = ""
            nz = g[g["nation"] != ""]["nation"]
            if not nz.empty:
                nation = nz.iloc[0]
            pos = ""
            if g["pos"].notna().any() and g["pos"].astype(str).str.strip().any():
                pos = g["pos"].iloc[0]
            for _, r in g.iterrows():
                rows.append(dict(league=league, season=r["season"], team=r["team"],
                                 player=player, nation=nation, pos=pos, age=r["age"],
                                 born=r["born"], mp=r["mp"], starts=r["starts"],
                                 minutes=r["minutes"], nineties=r["nineties"],
                                 goals=r["goals"], assists=r["assists"],
                                 g_plus_a=r["g_plus_a"], g_minus_pk=r["g_minus_pk"],
                                 pk=r["pk"], pkatt=r["pkatt"], crdy=r["crdy"],
                                 crdr=r["crdr"], goals_90=r["goals_90"],
                                 assists_90=r["assists_90"], g_plus_a_90=r["g_plus_a_90"],
                                 g_minus_pk_90=r["g_minus_pk_90"],
                                 g_plus_a_minus_pk_90=r["g_plus_a_minus_pk_90"],
                                 player_id=int(gid),
                                 match_score=round(float(r["match_score"]), 1),
                                 debut_season=debut,
                                 is_debut=1 if r["season"] == debut else 0,
                                 _end=r["_end"]))
        frame = pd.DataFrame(rows)
        frames.append(frame)
    res = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=OUT_COLS + ["_end"])
    res = res.sort_values(["player_id", "_end"])
    return res[OUT_COLS]


# --------------------------------------------------------------------------- build

def build(cfg):
    print("[ETL] %-7s %s..." % (cfg["slug"], cfg["mode"]), flush=True)
    df = load_league(cfg)
    res = enrich(df)
    min_s = res["season"].map(season_start).min()
    max_s = res["season"].map(season_end).max()
    out_name = cfg.get("out_name") or "%s_%d_%d.csv" % (cfg["slug"], min_s, max_s)
    out_path = os.path.join(CSV, cfg["folder"], out_name)
    res.to_csv(out_path, index=False, encoding="utf-8")
    n = len(res)
    base = BASELINE.get(cfg["slug"])
    warn = ""
    if base and abs(n - base) / base > 0.03:
        warn = "  << difiere de linea-base %d" % base
    print("  -> %s | %d filas | %d jugadores | temp %d%s%s"
          % (out_path, n, res["player_id"].nunique(), len(res["season"].unique()), warn, ""),
          flush=True)
    return n


def quarantine():
    os.makedirs(OBSOLETOS, exist_ok=True)
    for path in OBSOLETAS:
        if os.path.exists(path):
            dst = os.path.join(OBSOLETOS, os.path.basename(path))
            os.replace(path, dst)
            print("  movido ->", dst)
        else:
            print("  [skip] no existe:", path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="slug de liga a procesar")
    ap.add_argument("--quarantine", action="store_true")
    args = ap.parse_args()
    if args.quarantine:
        quarantine()
        return
    total = 0
    for cfg in LEAGUES:
        if args.only and cfg["slug"] != args.only:
            continue
        total += build(cfg)
    print("\nTotal filas (efectivas):", total)


if __name__ == "__main__":
    sys.exit(main() or 0)