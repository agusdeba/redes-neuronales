"""Validacion y control de calidad. Escribe reports/validation/*.csv y devuelve un resumen."""
from __future__ import annotations

import pandas as pd

from ..common import store
from ..common.config import REPORTS, cohort

OUT = REPORTS / "validation"


def coverage(players_all: pd.DataFrame, players: pd.DataFrame, perf: pd.DataFrame) -> pd.DataFrame:
    c = cohort()
    years = range(int(c["born_from"][:4]), int(c["born_to"][:4]) + 1)
    idx = pd.MultiIndex.from_product([list(c["countries"]), list(years)], names=["nationality", "birth_year"])
    if players.empty:
        return pd.DataFrame(index=idx).reset_index().assign(players=0)
    p = players.copy()
    p["dob_exact"] = p["dob_confidence"] == "exact"
    p["has_position"] = p["position_evidence"].notna()
    p["has_debut"] = p["debut_date"].notna()
    p["has_career"] = p["player_uid"].isin(perf["player_uid"]) if not perf.empty else False
    g = p.groupby(["nationality", "birth_year"])
    cov = pd.DataFrame({"players": g.size(), "pct_dob_exact": g["dob_exact"].mean() * 100,
                        "pct_position": g["has_position"].mean() * 100, "pct_debut": g["has_debut"].mean() * 100,
                        "pct_career": g["has_career"].mean() * 100})
    ex = players_all[players_all["inclusion_status"] != "included"].groupby(["nationality", "birth_year"]).size()
    cov["excluded_or_review"] = ex
    return cov.reindex(idx).fillna({"players": 0, "excluded_or_review": 0}).round(1).reset_index()


def sanity(stints: pd.DataFrame, perf: pd.DataFrame) -> pd.DataFrame:
    issues = []
    if not stints.empty:
        s = stints.copy()
        for col in ("minutes", "appearances", "goals"):
            s[col] = pd.to_numeric(s.get(col), errors="coerce")
        bad = s[s["minutes"] > 90 * s["appearances"] * 1.35]  # margen por alargue
        issues += [{"check": "minutos > 90*PJ*1.35", "player_uid": r.player_uid, "detail": f"{r.season} {r.competition_id}: {r.minutes} min en {r.appearances} PJ", "source": r.source} for r in bad.itertuples()]
        if "shots" in s.columns:
            b2 = s[pd.to_numeric(s["shots"], errors="coerce") < s["goals"]]
            issues += [{"check": "goles > tiros", "player_uid": r.player_uid, "detail": f"{r.season}", "source": r.source} for r in b2.itertuples()]
    if not perf.empty:
        p = perf[perf["appeared"] == 1]
        dup = p.groupby(["player_uid", "date"]).size()
        for (uid, date), n in dup[dup > 1].items():
            issues.append({"check": "dos partidos el mismo dia", "player_uid": uid, "detail": f"{date}: {n}", "source": "transfermarkt"})
        # dos clubes en la misma competicion y temporada (sin transferencia registrada)
        cc = p.groupby(["player_uid", "season", "competition_id"])["club_id"].nunique()
        tr = store.read_table("transfers")
        moved = set(zip(tr["player_uid"], tr["season"].astype(str))) if not tr.empty and "season" in tr else set()
        for (uid, season, comp), n in cc[cc > 1].items():
            if (uid, str(season)) not in moved:
                issues.append({"check": "2+ clubes misma competicion y temporada sin transferencia", "player_uid": uid,
                               "detail": f"{season} {comp}", "source": "transfermarkt"})
        if (p["minutes"] > 130).any():
            for r in p[p["minutes"] > 130].itertuples():
                issues.append({"check": "minutos de partido > 130", "player_uid": r.player_uid, "detail": f"{r.date} {r.minutes}", "source": "transfermarkt"})
    return pd.DataFrame(issues, columns=["check", "player_uid", "detail", "source"])


def audit_sample(players: pd.DataFrame, n_total: int = 30, seed: int = 42) -> pd.DataFrame:
    """Muestra estratificada pais x decada para auditoria manual (con URLs a revisar)."""
    if players.empty:
        return players
    p = players.copy()
    p["decade"] = (p["birth_year"] // 10) * 10
    strata = p.groupby(["nationality", "decade"])
    per = max(1, n_total // max(1, strata.ngroups))
    s = strata.apply(lambda g: g.sample(min(len(g), per), random_state=seed)).reset_index(drop=True)
    if len(s) < n_total:
        rest = p[~p["player_uid"].isin(s["player_uid"])]
        s = pd.concat([s, rest.sample(min(len(rest), n_total - len(s)), random_state=seed)])
    s["tm_url"] = s["tm_id"].map(lambda x: f"https://www.transfermarkt.com/x/profil/spieler/{x}" if pd.notna(x) else None)
    s["wikidata_url"] = s["qid"].map(lambda x: f"https://www.wikidata.org/wiki/{x}" if pd.notna(x) else None)
    s["audit_ok"] = ""
    s["audit_note"] = ""
    return s[["player_uid", "canonical_name", "nationality", "birth_year", "dob", "position_raw", "debut_date",
              "caps_tm_profile", "tm_url", "wikidata_url", "audit_ok", "audit_note"]]


def run() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    players_all = store.read_table("players_all")
    players = store.read_table("players")
    perf = store.read_table("match_performance")
    stints = store.read_table("career_stints")
    res = {"coverage": coverage(players_all, players, perf), "sanity": sanity(stints, perf),
           "audit_sample": audit_sample(players)}
    dups = players[players.duplicated("player_uid", keep=False)] if not players.empty else players
    res["duplicates"] = dups
    # posibles duplicados no resueltos: mismo nombre normalizado + misma DOB exacta
    if not players.empty:
        k = players.assign(_k=players["canonical_name"].str.lower() + "|" + players["dob"].astype(str))
        res["possible_duplicates"] = k[k.duplicated("_k", keep=False) & k["dob"].notna()].drop(columns="_k")
    for name, df in res.items():
        df.to_csv(OUT / f"{name}.csv", index=False, encoding="utf-8")
    return res
