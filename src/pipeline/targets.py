"""Targets (identicos a legacy/fase_d_targets.py, solo minutos; decision 5 del usuario).

  min_elite_puente = minutos de liga en 1as divisiones europeas elite + puente (toda la carrera, TM)
  target_standard  = caps >= 15 OR min_elite_puente >= 3500
  target_elite     = caps >= 30 OR min_elite_puente >= 8000

caps = caps de seleccion mayor del perfil TM (como antes). Si el perfil no los trae,
se usa el conteo de partidos de seleccion mayor con minutos (TM) y se marca.
Se agrega min_puente_uefa_fallback: minutos que entran a 'puente' solo por la regla
UEFA de fallback (p. ej. ligas menores de Europa), para auditar.
"""
from __future__ import annotations

import pandas as pd

from ..common import store
from ..common.config import cohort
from ..common.logs import get_logger

log = get_logger("pipeline.targets")


def run() -> dict:
    t = cohort()["targets"]
    players = store.read_table("players")
    perf = store.read_table("match_performance")
    nt = store.read_table("national_team_caps")
    if players.empty:
        return {}
    mins = perf.groupby(["player_uid", "category"])["minutes"].sum().unstack(fill_value=0) if not perf.empty else pd.DataFrame()
    get = lambda col: players["player_uid"].map(mins[col]).fillna(0) if col in mins else 0
    d = players[["player_uid", "canonical_name", "nationality", "birth_year", "tm_id", "caps_tm_profile"]].copy()
    d["min_elite"] = get("elite")
    d["min_puente"] = get("puente") + get("puente_uefa_fallback")
    d["min_puente_uefa_fallback"] = get("puente_uefa_fallback")
    d["min_elite_puente"] = d["min_elite"] + d["min_puente"]
    d["min_continental"] = get("continental")
    nt_apps = nt[nt["appeared"] == 1].groupby("player_uid").size() if not nt.empty else pd.Series(dtype=int)
    d["caps_tm_matches"] = d["player_uid"].map(nt_apps).fillna(0).astype(int)
    prof = pd.to_numeric(d["caps_tm_profile"], errors="coerce")
    d["caps"] = prof.fillna(d["caps_tm_matches"])
    d["caps_source"] = prof.notna().map({True: "tm_profile", False: "tm_matches"})
    has_career = d["player_uid"].isin(perf["player_uid"]) if not perf.empty else False
    d["tm_resuelto"] = (d["tm_id"].notna() & has_career).astype(int)
    m = d["tm_resuelto"] == 1
    d["target_standard"] = pd.NA
    d["target_elite"] = pd.NA
    d.loc[m, "target_standard"] = ((d.loc[m, "caps"] >= t["caps_standard"]) | (d.loc[m, "min_elite_puente"] >= t["min_standard"])).astype(int)
    d.loc[m, "target_elite"] = ((d.loc[m, "caps"] >= t["caps_elite"]) | (d.loc[m, "min_elite_puente"] >= t["min_elite"])).astype(int)
    store.write_table("targets", d)
    out = {"targets": d}
    for v in ("sa_clubs", "all_clubs"):
        f = store.read_table(f"features_u23_{v}")
        if f.empty:
            continue
        j = f.merge(d.drop(columns=["canonical_name", "nationality", "birth_year"]), left_on="player_id_global",
                    right_on="player_uid", how="left").drop(columns=["player_uid"])
        store.write_table(f"jugadores_target_ml_{v}", j)
        out[v] = j
        r = j["target_standard"].dropna()
        log.info(f"[{v}] filas={len(j)} con target={len(r)} standard=1: {int((r == 1).sum())} "
                 f"elite=1: {int((j['target_elite'] == 1).sum())}")
    return out
