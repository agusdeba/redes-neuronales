"""Features hasta los 23 (port de legacy/etl_ml_sudamericanos.py a las tablas canonicas).

Diferencias con el original, todas documentadas en docs/CAMBIOS_VS_LEGACY.md:
  - Fuente: partido a partido de Transfermarkt (edad exacta por fecha de partido) en vez
    de tablas de temporada FBref 2014+ (edad aproximada por temporada).
  - Poblacion: jugadores con inclusion_status == included (regla de posicion nueva).
  - Umbral: min_minutes_u23 = 1000 (config/cohort.yaml). El script original tenia
    default 1500; el usuario indico 1000.
  - Dos variantes, a pedido del usuario (decision 4):
      sa_clubs : solo clubes en ligas de los 7 paises + copas CONMEBOL (alcance del original)
      all_clubs: todas las competiciones oficiales de club (sin amistosos)
    En ambas se suma seleccion mayor para minutes_u23_total, como el original.
  - pk / pkatt / g_minus_pk: TM no los expone en performance-game; quedan nulos salvo
    que haya filas FBref del jugador (no se inventan).
Las columnas de salida son exactamente las del esquema original.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..common import store
from ..common.config import cohort
from ..common.logs import get_logger

log = get_logger("pipeline.features")

OUT_COLS = ["player_id_global", "player", "nation", "born", "pos", "debut_season", "debut_season_end", "debut_age",
            "cohort_mature", "club_mp", "club_starts", "club_minutes", "club_nineties", "club_goals", "club_assists",
            "club_g_plus_a", "club_g_minus_pk", "club_pk", "club_pkatt", "club_crdy", "club_crdr", "club_goals_90",
            "club_assists_90", "club_g_plus_a_90", "club_g_minus_pk_90", "club_g_plus_a_minus_pk_90", "club_n_seasons",
            "club_n_teams", "club_n_comps", "club_minutes_per_season", "club_minutes_libertadores",
            "club_minutes_sudamericana", "club_goals_season_max", "club_minutes_season_max", "nt_apps", "nt_starts",
            "nt_minutes", "nt_goals", "nt_g_plus_a", "nt_min_friendlies", "nt_min_wcq", "nt_min_worldcup",
            "nt_min_copa", "minutes_u23_total"]

LIBERTADORES = {"CLI"}
SUDAMERICANA = {"CS"}
CONMEBOL_CLUB = {"CLI", "CS", "RECO"}


def season_end_of(season) -> int | None:
    s = str(season or "")
    if "/" in s:  # TM '19/20'
        a, b = s.split("/")[:2]
        try:
            return 2000 + int(b) if int(b) < 50 else 1900 + int(b)
        except ValueError:
            return None
    digits = "".join(ch for ch in s if ch.isdigit())
    return int(digits[:4]) if len(digits) >= 4 else None


def age_at(dates: pd.Series, dob: str | None, birth_year) -> pd.Series:
    d = pd.to_datetime(dates, errors="coerce")
    if dob:
        return (d - pd.Timestamp(dob)).dt.days / 365.25
    if birth_year is not None and not pd.isna(birth_year):
        return d.dt.year - int(birth_year) - 0.5  # anio solo: punto medio
    return pd.Series(np.nan, index=dates.index)


def _sum(s):
    return float(s.sum()) if len(s) else 0.0


def build(variant: str = "sa_clubs") -> pd.DataFrame:
    c = cohort()
    max_age = c["max_feature_age"]
    players = store.read_table("players")
    perf = store.read_table("match_performance")
    nt = store.read_table("national_team_caps")
    comps = store.read_table("competitions")
    if players.empty or perf.empty:
        log.warning("sin players o match_performance; correr normalize primero")
        return pd.DataFrame(columns=OUT_COLS)
    tm_country_ids = {str(v["tm_country_id"]) for v in c["countries"].values()}
    def _idstr(v):
        try:
            return str(int(float(v)))
        except (TypeError, ValueError):
            return None
    comp_country = dict(zip(comps["competition_id"].astype(str), comps["country"].map(_idstr))) if not comps.empty else {}

    perf = perf[perf["category"] != "amistoso_club"].copy()
    if variant == "sa_clubs":
        keep = perf["competition_id"].astype(str).map(lambda x: comp_country.get(x) in tm_country_ids or x in CONMEBOL_CLUB)
        perf = perf[keep]
    by_p = dict(tuple(perf.groupby("player_uid")))
    by_nt = dict(tuple(nt.groupby("player_uid"))) if not nt.empty else {}
    fb = store.read_table("career_stints")
    fb = fb[fb["source"] == "fbref"] if not fb.empty and "source" in fb.columns else pd.DataFrame()

    rows = []
    for _, p in players.iterrows():
        uid = p["player_uid"]
        g = by_p.get(uid)
        if g is None or g.empty:
            continue
        g = g.copy()
        g["age"] = age_at(g["date"], p["dob"] if p.get("dob_confidence") == "exact" else None, p["birth_year"])
        played = g[g["appeared"] == 1].sort_values("date")
        if played.empty:
            continue
        debut = played.iloc[0]
        u = g[g["age"] <= max_age]
        up = u[u["appeared"] == 1]
        umin = _sum(u["minutes"])
        nineties = umin / 90.0 if umin > 0 else 0.0
        per90 = lambda v: round(v / nineties, 3) if nineties > 0 and v is not None and not pd.isna(v) else (0.0 if nineties == 0 else np.nan)
        goals, assists = _sum(u["goals"]), _sum(u["assists"])
        yel = u["yellow"].sum(min_count=1) if "yellow" in u else np.nan
        red = u["red"].sum(min_count=1) if "red" in u else np.nan
        starts = u["started"].sum(min_count=1) if "started" in u and u["started"].notna().any() else np.nan
        # pk desde FBref si existe (temporadas u23); si no, nulo
        pk = pkatt = np.nan
        if not fb.empty and "pk" in fb.columns:
            f = fb[fb["player_uid"] == uid]
            if not f.empty:
                fy = f["season"].map(season_end_of)
                f = f[(fy - (p["birth_year"] or 0)) <= max_age]
                pk = f["pk"].sum(min_count=1)
                pkatt = f["pkatt"].sum(min_count=1) if "pkatt" in f else np.nan
        seasons = u.groupby(["season", "competition_id", "club_id"])
        n_seasons = u["season"].nunique()
        rec = {
            "player_id_global": uid, "player": p["canonical_name"], "nation": p["nationality"], "born": p["birth_year"],
            "pos": p.get("position_raw"), "debut_season": debut["season"], "debut_season_end": season_end_of(debut["season"]),
            "debut_age": round(float(debut["age"]), 2) if not pd.isna(debut["age"]) else None,
            "cohort_mature": int(int(c["born_from"][:4]) <= int(p["birth_year"]) <= int(c["born_to"][:4])),
            "club_mp": float(len(up)), "club_starts": starts, "club_minutes": umin, "club_nineties": round(nineties, 2),
            "club_goals": goals, "club_assists": assists, "club_g_plus_a": goals + assists,
            "club_g_minus_pk": goals - pk if not pd.isna(pk) else np.nan, "club_pk": pk, "club_pkatt": pkatt,
            "club_crdy": yel, "club_crdr": red, "club_goals_90": per90(goals), "club_assists_90": per90(assists),
            "club_g_plus_a_90": per90(goals + assists),
            "club_g_minus_pk_90": per90(goals - pk) if not pd.isna(pk) else np.nan,
            "club_g_plus_a_minus_pk_90": per90(goals + assists - pk) if not pd.isna(pk) else np.nan,
            "club_n_seasons": n_seasons, "club_n_teams": u["club_id"].nunique(), "club_n_comps": u["competition_id"].nunique(),
            "club_minutes_per_season": round(umin / n_seasons, 1) if n_seasons else 0.0,
            "club_minutes_libertadores": _sum(u.loc[u["competition_id"].astype(str).isin(LIBERTADORES), "minutes"]),
            "club_minutes_sudamericana": _sum(u.loc[u["competition_id"].astype(str).isin(SUDAMERICANA), "minutes"]),
            "club_goals_season_max": float(seasons["goals"].sum().max()) if len(u) else 0.0,
            "club_minutes_season_max": float(seasons["minutes"].sum().max()) if len(u) else 0.0,
        }
        n = by_nt.get(uid)
        if n is not None and not n.empty:
            n = n.copy()
            n["age"] = age_at(n["date"], p["dob"] if p.get("dob_confidence") == "exact" else None, p["birth_year"])
            n = n[n["age"] <= max_age]
        else:
            n = pd.DataFrame(columns=["minutes", "appeared", "started", "goals", "assists", "tournament"])
        tour = n["tournament"].astype(str) if len(n) else pd.Series(dtype=str)
        rec.update({
            "nt_apps": float(n["appeared"].sum()) if len(n) else 0.0,
            "nt_starts": float(pd.to_numeric(n["started"], errors="coerce").sum()) if len(n) else 0.0,
            "nt_minutes": _sum(n["minutes"]) if len(n) else 0.0,
            "nt_goals": _sum(n["goals"]) if len(n) else 0.0,
            "nt_g_plus_a": (_sum(n["goals"]) + _sum(n["assists"])) if len(n) else 0.0,
            "nt_min_friendlies": _sum(n.loc[tour == "FS", "minutes"]) if len(n) else 0.0,
            "nt_min_wcq": _sum(n.loc[tour.str.startswith("WMQ"), "minutes"]) if len(n) else 0.0,
            "nt_min_worldcup": _sum(n.loc[tour == "FIWC", "minutes"]) if len(n) else 0.0,
            "nt_min_copa": _sum(n.loc[tour == "COPA", "minutes"]) if len(n) else 0.0,
        })
        rec["minutes_u23_total"] = round(rec["club_minutes"] + rec["nt_minutes"], 1)
        rows.append(rec)
    df = pd.DataFrame(rows, columns=OUT_COLS)
    before = len(df)
    df = df[df["minutes_u23_total"] >= c["min_minutes_u23"]].sort_values("player_id_global").reset_index(drop=True)
    log.info(f"[{variant}] con carrera: {before} | pasan >= {c['min_minutes_u23']} min hasta {max_age}: {len(df)}")
    return df


def run():
    out = {}
    for v in ("sa_clubs", "all_clubs"):
        df = build(v)
        store.write_table(f"features_u23_{v}", df)
        out[v] = df
    return out
