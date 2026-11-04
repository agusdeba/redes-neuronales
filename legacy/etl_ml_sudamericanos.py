#!/usr/bin/env python3
"""Fase B: dataset de delanteros sudamericanos, features hasta los 23.

Genera csv/ml/jugadores_sudamericanos_etl.csv (1 fila por jugador) con:
  - conecta jugadores entre las 7 competiciones de club sudamericanas
    (Argentina, Brasil, Uruguay, Colombia, Ecuador, Libertadores, Sudamericana)
    usando el mismo Matcher fuzzy del ETL (id GLOBAL entre ligas).
  - poblacion candidata = delantero (cualquier Pos contiene FW) con mp>0 en clubes SA.
  - filtro base: >=1500 minutos acumulados antes de los 23 (clubes SA + seleccion).
  - features "resumen hasta los 23": sumas/tasas/derivadas de clubes SA + columnas
    SEPARADAS de Seleccion Mayor (amistosos, eliminatorias, Copa America, Mundial).

El target (Transfermarkt) y el embudo final corresponden a las fases C/D/E.

  python etl_ml_sudamericanos.py
  python etl_ml_sudamericanos.py --min-total-minutes-u23 1500 --mature-born-until 2000
"""

import argparse
import os
import sys

import pandas as pd

from etl_fbref_unico import FUZZY_MIN, Matcher, norm, season_end
from rapidfuzz import fuzz

ROOT = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(ROOT, "csv")

MAX_FEATURE_AGE = 23
CLUB_FILES = [
    ("ARG-Primera", "csv/argentina/argentina_2014_2025.csv"),
    ("BRA-SerieA", "csv/brasil/brasil_2014_2025.csv"),
    ("URU-Primera", "csv/uruguay/uruguay_2014_2025.csv"),
    ("COL-PrimeraA", "csv/colombia/colombia_2015_2025.csv"),
    ("ECU-SerieA", "csv/ecuador/ecuador_2014_2025.csv"),
    ("INT-Libertadores", "csv/libertadores/libertadores_2014_2025.csv"),
    ("INT-Sudamericana", "csv/sudamericana/sudamericana_2014_2025.csv"),
]

NT_FILES = [
    ("friendlies", "csv/friendlies/friendlies_2014_2025.csv"),
    ("wcq", "csv/wcq_conmebol/wcq_conmebol_2014_2026.csv"),
    ("worldcup", "csv/world_cup/world_cup_1994_2026.csv"),
    ("copa", "csv/copa_america/copa_america_2015_2024.csv"),
]

NUM_COLS = ["mp", "starts", "minutes", "nineties", "goals", "assists", "g_plus_a",
            "g_minus_pk", "pk", "pkatt", "crdy", "crdr", "goals_90", "assists_90",
            "g_plus_a_90", "g_minus_pk_90", "g_plus_a_minus_pk_90"]


class FindMatcher(Matcher):
    """Matcher con busqueda estatica (no crea grupos): asigna a grupos existentes."""

    def find(self, norm_name, born, nation=""):
        if not norm_name:
            return None, 0.0
        key = self._key(born, norm_name[:1])
        bk = self.buckets.get(key)
        if not bk:
            return None, 0.0
        if norm_name in bk["map"]:
            gid = bk["map"][norm_name]
            g = self.groups[gid]
            if nation and g["nations"] and nation not in g["nations"]:
                pass  # sigue buscando por fuzzy
            else:
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
        return best_g, best_score


NATION_ALIAS = {"col": "co", "ecu": "ec", "ven": "ve", "pan": "pa", "bra": "br",
                "arg": "ar", "uru": "uy", "ola": "", "nan": ""}


def clean_nation(v):
    if pd.isna(v):
        return ""
    t = str(v).strip()
    if not t:
        return ""
    c = t.split()[0].lower()
    return NATION_ALIAS.get(c, c)


def load(path):
    df = pd.read_csv(path, low_memory=False)
    for c in NUM_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["born"] = pd.to_numeric(df["born"], errors="coerce")
    df["age"] = pd.to_numeric(df["age"], errors="coerce")
    df["nation"] = df["nation"].map(clean_nation)
    return df


def eff_age(age, season_label, born):
    if pd.notna(age):
        return age
    if pd.notna(born):
        return season_end(season_label) - born
    return float("nan")


def year_family(pos):
    p = norm(str(pos))
    return "FW" if p and "fw" in p else ""  # 'fw' -> FW


def positive_minutes(m):
    return m if pd.notna(m) and m > 0 else 0.0


def series_max(s):
    if s.empty or s.dropna().empty:
        return 0.0
    return float(s.max())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-total-minutes-u23", type=float, default=1500.0)
    ap.add_argument("--mature-born-from", type=int, default=1995)
    ap.add_argument("--mature-born-until", type=int, default=2000)
    ap.add_argument("--out", default=os.path.join(CSV, "ml", "jugadores_sudamericanos_etl.csv"))
    args = ap.parse_args()

    # --------------------------------------------------------- clubes SA
    club = pd.concat([load(os.path.join(ROOT, p)) for _, p in CLUB_FILES],
                     ignore_index=True)
    club["_norm"] = club["player"].map(norm)
    club["_end"] = club["season"].map(season_end)
    club["_age"] = [eff_age(a, s, b) for a, s, b in zip(club["age"], club["season"], club["born"])]
    club["_fw"] = club["pos"].map(year_family)

    matcher = FindMatcher()
    ids, scores = [], []
    for n, born, nat in zip(club["_norm"], club["born"], club["nation"]):
        gid, sc = matcher.add(n, born, nat) if n else (None, 0.0)
        ids.append(gid)
        scores.append(sc)
    club["pid"] = ids
    club["score"] = scores
    club = club[club["pid"].notna()]
    club["pid"] = club["pid"].astype(int)

    # --------------------------------------------------------- candidatos FW
    played = club[club["mp"] > 0]
    fw_rows = club[club["_fw"] == "FW"]
    total_forwards = played[played["pid"].isin(set(fw_rows["pid"]))]["pid"].nunique()
    print(f"[FASE B] delanteros totales (mp>0 en clubes SA, Pos con FW): {total_forwards}")

    # --------------------------------------------------------- features por jugador
    records = []
    for pid in sorted(played[played["pid"].isin(set(fw_rows["pid"]))]["pid"].unique()):
        rows = club[club["pid"] == pid]

        player = Matcher.canonical(rows["player"].dropna().astype(str).tolist())
        nz = rows[rows["nation"].notna() & (rows["nation"].astype(str).str.strip() != "")]
        nation = nz["nation"].iloc[0] if not nz.empty else ""
        borns = rows["born"].dropna()
        born = float(borns.iloc[0]) if not borns.empty else float("nan")
        poss = rows[rows["pos"].notna() & rows["pos"].astype(str).str.strip().ne("")]
        pos = poss["pos"].mode().iloc[0] if not poss.empty else ""

        # debut (cualquier edad) = primer partido de club
        d = played[played["pid"] == pid].sort_values("_end")
        debut = d.iloc[0]
        debut_season = str(debut["season"])
        debut_age = float(debut["_age"])

        # u23: filas de club con edad <= 23
        u = rows[rows["_age"] <= MAX_FEATURE_AGE]
        umin = positive_minutes(u["minutes"].sum()) if not u.empty else 0.0
        n_seasons = u["season"].nunique() if not u.empty else 0
        n_teams = u["team"].nunique() if not u.empty else 0
        n_comps = u["league"].nunique() if not u.empty else 0

        sums = {c: (positive_minutes(u[c].sum()) if c == "minutes"
                    else (u[c].sum(min_count=1) if not u.empty else 0.0)) for c in NUM_COLS}
        nineties = umin / 90.0 if umin > 0 else 0.0
        def per90(v):
            return round(v / nineties, 3) if nineties > 0 else 0.0

        record = {
            "player_id_global": int(pid),
            "player": player,
            "nation": nation,
            "born": born,
            "pos": pos,
            "debut_season": debut_season,
            "debut_season_end": season_end(debut_season),
            "debut_age": round(debut_age, 2) if pd.notna(debut_age) else None,
            "cohort_mature": int(pd.notna(born) and args.mature_born_from <= born <= args.mature_born_until),
            # clubes SA, hasta los 23
            "club_mp": sums["mp"], "club_starts": sums["starts"], "club_minutes": umin,
            "club_nineties": round(nineties, 2),
            "club_goals": sums["goals"], "club_assists": sums["assists"],
            "club_g_plus_a": sums["g_plus_a"], "club_g_minus_pk": sums["g_minus_pk"],
            "club_pk": sums["pk"], "club_pkatt": sums["pkatt"],
            "club_crdy": sums["crdy"], "club_crdr": sums["crdr"],
            "club_goals_90": per90(sums["goals"]),
            "club_assists_90": per90(sums["assists"]),
            "club_g_plus_a_90": per90(sums["g_plus_a"]),
            "club_g_minus_pk_90": per90(sums["g_minus_pk"]),
            "club_g_plus_a_minus_pk_90": per90(sums["g_plus_a"] - sums["pk"]),
            "club_n_seasons": n_seasons, "club_n_teams": n_teams, "club_n_comps": n_comps,
            "club_minutes_per_season": round(umin / n_seasons, 1) if n_seasons else 0.0,
            "club_minutes_libertadores": positive_minutes(u.loc[u["league"] == "INT-Libertadores", "minutes"].sum()) if not u.empty else 0.0,
            "club_minutes_sudamericana": positive_minutes(u.loc[u["league"] == "INT-Sudamericana", "minutes"].sum()) if not u.empty else 0.0,
            "club_goals_season_max": series_max(u["goals"]) if not u.empty else 0.0,
            "club_minutes_season_max": series_max(u["minutes"]) if not u.empty else 0.0,
        }
        records.append((pid, record))

    # --------------------------------------------------------- features de seleccion
    nt_agg = {}
    for key, path in NT_FILES:
        df = load(os.path.join(ROOT, path))
        df["_norm"] = df["player"].map(norm)
        df["_age"] = [eff_age(a, s, b) for a, s, b in zip(df["age"], df["season"], df["born"])]
        for _, r in df.iterrows():
            if r["_age"] > MAX_FEATURE_AGE or pd.isna(r["_age"]):
                continue
            # Las filas de seleccion se adhieren por nombre+nacimiento (sin filtro
            # de nacion: friendlies/wcq/copa no traen nation y world_cup trae el
            # nombre completo del pais, no el codigo).
            gid, _sc = matcher.find(r["_norm"], r["born"], "")
            if gid is None:
                continue
            rec = nt_agg.setdefault(gid, {"apps": 0.0, "starts": 0.0, "minutes": 0.0,
                                          "goals": 0.0, "g_plus_a": 0.0,
                                          "min_friendlies": 0.0, "min_wcq": 0.0,
                                          "min_worldcup": 0.0, "min_copa": 0.0})
            mp = positive_minutes(r["mp"]); mins = positive_minutes(r["minutes"])
            rec["apps"] += mp
            rec["starts"] += positive_minutes(r["starts"])
            rec["minutes"] += mins
            rec["goals"] += positive_minutes(r["goals"])
            rec["g_plus_a"] += positive_minutes(r["g_plus_a"])
            rec["min_" + key] += mins

    # --------------------------------------------------------- dataset final
    rows = []
    for pid, record in records:
        nt = nt_agg.get(pid, {})
        record.update({
            "nt_apps": nt.get("apps", 0.0), "nt_starts": nt.get("starts", 0.0),
            "nt_minutes": nt.get("minutes", 0.0), "nt_goals": nt.get("goals", 0.0),
            "nt_g_plus_a": nt.get("g_plus_a", 0.0),
            "nt_min_friendlies": nt.get("min_friendlies", 0.0),
            "nt_min_wcq": nt.get("min_wcq", 0.0),
            "nt_min_worldcup": nt.get("min_worldcup", 0.0),
            "nt_min_copa": nt.get("min_copa", 0.0),
            "minutes_u23_total": round(record["club_minutes"] + nt.get("minutes", 0.0), 1),
        })
        rows.append(record)

    df = pd.DataFrame(rows)
    df = df[df["minutes_u23_total"] >= args.min_total_minutes_u23]

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    df = df.sort_values("player_id_global").reset_index(drop=True)
    df.to_csv(args.out, index=False, encoding="utf-8")

    pasaron = len(df)
    print(f"[FASE B] pasaron filtro (>= {args.min_total_minutes_u23:g} min hasta 23): {pasaron}")
    total = len(df) + 0.0
    aux = df[df["cohort_mature"] == 1]
    print(f"[FASE B] cohorte madura (born {args.mature_born_from}-{args.mature_born_until}): {len(aux)} de {pasaron}")
    print("[FASE B] por nacion:")
    print(df["nation"].value_counts().head(12).to_string())
    print(f"\n[FASE B] guardado -> {args.out} | columnas: {len(df.columns)} | filas: {len(df)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())