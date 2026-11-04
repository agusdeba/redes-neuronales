"""Normalizacion + identidad + posiciones => tablas canonicas en data/processed/.

Lee todo lo que haya en data/interim/ (cualquier subconjunto de fuentes) y construye:
  players, player_identity, career_stints, match_performance, national_team_caps,
  youth_caps, transfers, competitions, conflicts, review_queue, excluded_players,
  seed_candidates.
Es determinista e idempotente: volver a correr reescribe las tablas completas.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone

import pandas as pd

from ..common import store
from ..common.config import cohort
from ..common.logs import get_logger
from ..common.textnorm import norm_name
from . import identity, positions as pos

log = get_logger("pipeline.normalize")

TM_COUNTRY = {"Argentina": "ARG", "Brazil": "BRA", "Chile": "CHI", "Uruguay": "URU", "Paraguay": "PAR",
              "Colombia": "COL", "Ecuador": "ECU"}
FBREF_NATION = {"ARG": "ARG", "BRA": "BRA", "CHI": "CHI", "URU": "URU", "PAR": "PAR", "COL": "COL", "ECU": "ECU"}


PLAYER_COLS = ["player_uid", "canonical_name", "full_name", "dob", "dob_confidence", "birth_year", "nationality",
               "nationality_secondary", "citizenship_all", "position_group", "position_raw", "position_evidence",
               "inclusion_status", "inclusion_reason", "height", "foot", "debut_date", "retirement_date", "is_active",
               "tm_id", "qid", "fbref_id", "nft_id", "worldfootball_id", "caps_tm_profile", "nt_goals_tm_profile",
               "seeds", "source_primary", "last_updated"]


def _nn(v):
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    s = str(v).strip()
    return None if s in ("", "nan", "None", "NaT") else s


def _list(v):
    if isinstance(v, (list, tuple)):
        return list(v)
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return []
    try:
        import numpy as np
        if isinstance(v, np.ndarray):
            return list(v)
    except ImportError:  # pragma: no cover
        pass
    return [v]


def _records(df: pd.DataFrame) -> list[dict]:
    return [] if df is None or df.empty else df.to_dict("records")


def tm_nationalities(names) -> list[str]:
    return [TM_COUNTRY[n] for n in _list(names) if n in TM_COUNTRY]


# ---------------------------------------------------------------------------- candidatos
def collect_candidates() -> list[dict]:
    cands: list[dict] = []
    for r in _records(store.read_entity("wikidata", "players")):
        cands.append({"seed": "wikidata", "source": "wikidata", "qid": _nn(r.get("qid")), "tm_id": _nn(r.get("tm_id")),
                      "fbref_id": _nn(r.get("fbref_id")), "nft_id": _nn(r.get("nft_id")),
                      "worldfootball_id": _nn(r.get("worldfootball_id")), "espn_id": _nn(r.get("espn_id")),
                      "name": r.get("name"), "aliases": _list(r.get("aliases")), "full_name": _nn(r.get("birth_name")),
                      "dob": _nn(r.get("dob")), "birth_year": r.get("birth_year"),
                      "dob_confidence": r.get("dob_confidence"), "nationalities": [r.get("nationality")],
                      "pos_wikidata": _list(r.get("positions")), "source_url": r.get("source_url"),
                      "retrieved_at": r.get("retrieved_at")})
    for ent in ("squads", "nt_squads"):
        for r in _records(store.read_entity("transfermarkt", ent)):
            dob = _nn(r.get("dob"))
            nats = tm_nationalities(r.get("nationalities")) or ([r.get("country")] if ent == "nt_squads" else [])
            cands.append({"seed": r.get("seed"), "source": "transfermarkt", "tm_id": _nn(r.get("tm_id")),
                          "name": r.get("name"), "dob": dob, "birth_year": int(dob[:4]) if dob else None,
                          "dob_confidence": "exact" if dob else None, "nationalities": nats,
                          "pos_tm_squad": _nn(r.get("position")),
                          "club_seasons": [(norm_name(r.get("club_name")), int(r.get("season")))] if r.get("season") else [],
                          "source_url": r.get("source_url"), "retrieved_at": r.get("retrieved_at")})
    for r in _records(store.read_entity("wikipedia", "category_members")):
        if _nn(r.get("qid")):
            cands.append({"seed": "wikipedia", "source": "wikipedia", "qid": r.get("qid"), "name": r.get("title"),
                          "nationalities": [r.get("country")], "source_url": r.get("source_url"),
                          "retrieved_at": r.get("retrieved_at")})
    for r in _records(store.read_entity("fbref", "season_stats")):
        nat = FBREF_NATION.get(str(r.get("nation") or "").upper())
        born = r.get("born")
        born = int(born) if born is not None and not pd.isna(born) else None
        season = str(r.get("season") or "")
        cands.append({"seed": "fbref_" + str(r.get("competition_type") or "comp"), "source": "fbref",
                      "fbref_id": _nn(r.get("player_fbref_id")), "name": r.get("player"), "birth_year": born,
                      "dob_confidence": "year_only" if born else None, "nationalities": [nat] if nat else [],
                      "pos_fbref": _nn(r.get("pos")),
                      "club_seasons": [(norm_name(r.get("team")), int(season[:4]))] if season[:4].isdigit() else [],
                      "source_url": r.get("source_url"), "retrieved_at": r.get("retrieved_at")})
    for r in _records(store.read_entity("transfermarkt", "profile")):
        cands.append({"seed": "tm_profile", "source": "transfermarkt", "tm_id": _nn(r.get("tm_id")),
                      "name": r.get("name"), "full_name": _nn(r.get("full_name")), "dob": _nn(r.get("dob")),
                      "birth_year": int(r["dob"][:4]) if _nn(r.get("dob")) else None,
                      "dob_confidence": "exact" if _nn(r.get("dob")) else None,
                      "nationalities": tm_nationalities(r.get("citizenship")),
                      "citizenship_all": _list(r.get("citizenship")),
                      "pos_tm_main": _nn(r.get("position_main")) or _nn(r.get("position_raw")),
                      "pos_tm_other": _list(r.get("position_other")), "foot": _nn(r.get("foot")),
                      "height_cm": r.get("height_cm"), "retired_since": _nn(r.get("retired_since")),
                      "caps_profile": r.get("caps_profile"), "caps_parsed": r.get("caps_parsed"),
                      "nt_goals_profile": r.get("nt_goals_profile"), "slug": r.get("slug"),
                      "source_url": r.get("source_url"), "retrieved_at": r.get("retrieved_at")})
    return cands


# ---------------------------------------------------------------------------- jugadores
def build_players(cands: list[dict]):
    c = cohort()
    y0, y1 = int(c["born_from"][:4]), int(c["born_to"][:4])
    countries = set(c["countries"])

    # FBref sin id: pseudo-id por nombre+anio+nacion (se intentara unir por fuzzy)
    for r in cands:
        if r["source"] == "fbref" and not r.get("fbref_id"):
            r["_orphan"] = True
    strong = [r for r in cands if not r.get("_orphan")]
    roots = identity.cluster_records(strong)
    clusters: dict = defaultdict(list)
    for i, root in roots.items():
        clusters[root].append(strong[i])

    players, ident, conflicts, review = [], [], [], []
    by_uid: dict[str, list[dict]] = {}
    for recs in clusters.values():
        tm = next((r["tm_id"] for r in recs if r.get("tm_id")), None)
        qid = next((r["qid"] for r in recs if r.get("qid")), None)
        fb = next((r["fbref_id"] for r in recs if r.get("fbref_id")), None)
        uid = identity.make_uid(tm, qid, fb, fallback=norm_name(recs[0].get("name")))
        by_uid[uid] = recs

    # adjuntar huerfanos FBref
    summaries = [summarize(uid, recs) for uid, recs in by_uid.items()]
    blocks = identity.build_blocks(summaries)
    for r in [x for x in cands if x.get("_orphan")]:
        nat = (r.get("nationalities") or [None])[0]
        cand_pool = blocks.get((r.get("birth_year"), nat), []) + blocks.get((r.get("birth_year"), None), [])
        if r.get("dob_confidence") == "year_only" and r.get("birth_year"):
            for d in (-1, 1):
                cand_pool += blocks.get((r["birth_year"] + d, nat), [])
        res = identity.fuzzy_attach({**r, "nationality": nat, "club_seasons": set(r.get("club_seasons") or [])}, cand_pool)
        if res["status"] == "mapped":
            by_uid[res["uid"]].append({**r, "_match": res})
        else:
            key = f"fbn:{norm_name(r.get('name'))}:{r.get('birth_year')}:{nat}"
            uid = identity.make_uid(fallback=key)
            if res["status"] == "review":
                review.append({"player_uid": uid, "type": "identity", "name": r.get("name"),
                               "birth_year": r.get("birth_year"), "nationality": nat,
                               "candidate_uid": res.get("uid"), "score": res.get("score"), "reason": res["note"],
                               "source": "fbref", "source_url": r.get("source_url")})
            by_uid.setdefault(uid, []).append({**r, "_match": res})

    decisions = pos.manual_decisions()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    seeds = []
    for uid, recs in by_uid.items():
        s = summarize(uid, recs)
        for r in recs:
            seeds.append({"player_uid": uid, "seed": r.get("seed"), "source": r.get("source"),
                          "name": r.get("name"), "source_url": r.get("source_url")})
        in_years = s["birth_year"] is not None and y0 <= int(s["birth_year"]) <= y1
        in_country = bool(set(s["nationalities"]) & countries)
        if not (in_years and in_country):
            continue
        # conflictos de DOB / nacionalidad entre fuentes
        dobs = {r["source"]: r["dob"] for r in recs if r.get("dob")}
        if len(set(dobs.values())) > 1:
            items = sorted(dobs.items())
            for (sa, va), (sb, vb) in zip(items, items[1:]):
                if va != vb:
                    conflicts.append({"player_uid": uid, "field": "dob", "source_a": sa, "value_a": va,
                                      "source_b": sb, "value_b": vb, "resolution": "transfermarkt" if "transfermarkt" in dobs else sa,
                                      "reviewed": False})
        # posicion
        ev = pos.PositionEvidence()
        if s.get("pos_tm_main"):
            ev.add("transfermarkt", pos.classify_label("transfermarkt", s["pos_tm_main"]),
                   [pos.classify_label("transfermarkt", o) for o in s.get("pos_tm_other", [])], s["pos_tm_main"])
        elif s.get("pos_tm_squad"):
            ev.add("transfermarkt", pos.classify_label("transfermarkt", s["pos_tm_squad"]), [], s["pos_tm_squad"])
        if s.get("pos_fbref"):
            prim, sec = fbref_majority(s["pos_fbref"])
            ev.add("fbref", prim, sec, ",".join(s["pos_fbref"]))
        if s.get("pos_wikidata"):
            gs = [pos.classify_label("wikidata", p) for p in s["pos_wikidata"]]
            gs = [g for g in gs if g]
            if gs:
                ev.add("wikidata", "attack" if "attack" in gs else gs[0], [], ";".join(s["pos_wikidata"]))
        status, group, reason = pos.decide(ev)
        manual = decisions.get(uid)
        if manual in ("include", "exclude"):
            status, reason = ("included" if manual == "include" else "excluded"), f"decision manual ({manual}); " + reason
        prim_nat = s["nationality"]
        players.append({
            "player_uid": uid, "canonical_name": s["name"], "full_name": s.get("full_name"),
            "dob": s["dob"], "dob_confidence": s["dob_confidence"], "birth_year": s["birth_year"],
            "nationality": prim_nat,
            "nationality_secondary": ";".join(n for n in s["nationalities"] if n != prim_nat) or None,
            "citizenship_all": ";".join(s.get("citizenship_all") or []) or None,
            "position_group": group, "position_raw": "; ".join(f"{k}={v}" for k, v in ev.raw.items()) or None,
            "position_evidence": ",".join(sorted(set(ev.primary) | set(ev.secondary))) or None,
            "inclusion_status": status, "inclusion_reason": reason,
            "height": s.get("height_cm"), "foot": s.get("foot"), "debut_date": None, "retirement_date": s.get("retired_since"),
            "is_active": None if s.get("retired_since") is None and not s.get("tm_id") else s.get("retired_since") is None,
            "tm_id": s.get("tm_id"), "qid": s.get("qid"), "fbref_id": s.get("fbref_id"),
            "nft_id": s.get("nft_id"), "worldfootball_id": s.get("worldfootball_id"),
            "caps_tm_profile": s.get("caps_profile"), "nt_goals_tm_profile": s.get("nt_goals_profile"),
            "seeds": ";".join(sorted({r.get("seed") or "" for r in recs} - {""})),
            "source_primary": "transfermarkt" if s.get("tm_id") else ("wikidata" if s.get("qid") else "fbref"),
            "last_updated": now,
        })
        for r in recs:
            for k in ("tm_id", "qid", "fbref_id", "nft_id", "worldfootball_id", "espn_id"):
                if r.get(k):
                    m = r.get("_match") or {}
                    ident.append({"player_uid": uid, "source": {"qid": "wikidata"}.get(k, k.replace("_id", "")),
                                  "source_id": r[k], "source_url": r.get("source_url"),
                                  "match_score": m.get("score", 100.0), "match_method": m.get("method") or "exact_id",
                                  "verified": m.get("method") is None, "notes": r.get("seed")})
            if r.get("_orphan"):
                m = r.get("_match") or {}
                ident.append({"player_uid": uid, "source": "fbref_name", "source_id": norm_name(r.get("name")),
                              "source_url": r.get("source_url"), "match_score": m.get("score"),
                              "match_method": m.get("method") or "new_cluster", "verified": False,
                              "notes": m.get("note")})
        if status == "review":
            review.append({"player_uid": uid, "type": "position", "name": s["name"], "birth_year": s["birth_year"],
                           "nationality": prim_nat, "candidate_uid": None, "score": None,
                           "reason": reason, "source": ev.raw and ",".join(ev.raw), "source_url": s.get("profile_url")})
    pl = pd.DataFrame(players, columns=PLAYER_COLS).drop_duplicates("player_uid")
    idt = pd.DataFrame(ident, columns=["player_uid", "source", "source_id", "source_url", "match_score",
                                       "match_method", "verified", "notes"]).drop_duplicates(["player_uid", "source", "source_id"])
    return pl, idt, pd.DataFrame(conflicts), pd.DataFrame(review), pd.DataFrame(seeds)


def fbref_majority(pos_list: list[str]):
    """Posicion primaria FBref = la mas frecuente entre temporadas (primer token de cada temporada)."""
    prims, secs = Counter(), set()
    for p in pos_list:
        pr, sc = pos.fbref_groups(p)
        if pr:
            prims[pr] += 1
        secs.update(sc)
    if not prims:
        return None, list(secs)
    top = prims.most_common(1)[0][0]
    others = set(prims) - {top}
    return top, list(secs | others)


def summarize(uid: str, recs: list[dict]) -> dict:
    """Fusiona registros de un cluster con prioridad TM perfil > Wikidata > TM plantel > FBref."""
    prio = {"tm_profile": 0, "wikidata": 1, "tm_league": 2, "tm_national_team": 2, "wikipedia": 4}
    recs_sorted = sorted(recs, key=lambda r: prio.get(r.get("seed"), 3))

    def first(k):
        for r in recs_sorted:
            v = r.get(k)
            if v not in (None, "", [], "nan") and not (isinstance(v, float) and pd.isna(v)):
                return v
        return None

    dob = first("dob")
    by = first("birth_year")
    by = int(dob[:4]) if dob else (int(by) if by is not None else None)
    conf = "exact" if dob else ("year_only" if by else None)
    nats: list[str] = []
    for r in recs_sorted:
        for n in r.get("nationalities") or []:
            if n and n not in nats:
                nats.append(n)
    names = [r.get("name") for r in recs_sorted if r.get("name")] + [a for r in recs for a in (r.get("aliases") or [])]
    club_seasons = set()
    for r in recs:
        club_seasons.update(r.get("club_seasons") or [])
    tm_prof = next((r for r in recs_sorted if r.get("seed") == "tm_profile"), {})
    return {"uid": uid, "name": first("name"), "full_name": first("full_name"), "names": names, "dob": dob,
            "birth_year": by, "dob_confidence": conf, "nationalities": nats,
            "nationality": nats[0] if nats else None, "tm_id": first("tm_id"), "qid": first("qid"),
            "fbref_id": first("fbref_id"), "nft_id": first("nft_id"), "worldfootball_id": first("worldfootball_id"),
            "pos_tm_main": tm_prof.get("pos_tm_main"), "pos_tm_other": tm_prof.get("pos_tm_other") or [],
            "pos_tm_squad": first("pos_tm_squad"),
            "pos_fbref": [r["pos_fbref"] for r in recs if r.get("pos_fbref")],
            "pos_wikidata": first("pos_wikidata") or [], "foot": first("foot"), "height_cm": first("height_cm"),
            "retired_since": first("retired_since"), "caps_profile": tm_prof.get("caps_profile"),
            "nt_goals_profile": tm_prof.get("nt_goals_profile"), "citizenship_all": tm_prof.get("citizenship_all"),
            "club_seasons": club_seasons,
            "profile_url": tm_prof.get("source_url")}


# ---------------------------------------------------------------------------- carrera
def classify_competition(cid: str, meta: dict) -> str:
    cc = cohort()["competitions"]
    cid = str(cid)
    if cid in cc["elite"]:
        return "elite"
    if cid in cc["puente"]:
        return "puente"
    if cid in cc["continental"]:
        return "continental"
    if cid in cc["nt_senior"]:
        return "seleccion"
    if cid in cc["nt_youth"]:
        return "seleccion_juvenil"
    if cid in cc["club_friendly"]:
        return "amistoso_club"
    m = meta.get(cid) or {}
    if str(m.get("type_id")) == "1" and int(m.get("confederation_id") or 0) == int(cc["uefa_confederation_id"]):
        return "puente_uefa_fallback"  # se suma a puente, pero queda auditable
    return "otra"


def build_career(players: pd.DataFrame):
    c = cohort()
    tm_to_uid = dict(zip(players["tm_id"].astype(str), players["player_uid"])) if not players.empty else {}
    matches = store.read_entity("transfermarkt", "matches")
    comps = store.read_entity("transfermarkt", "competitions")
    meta = {str(r["competition_id"]): r for r in _records(comps)}
    squads = pd.concat([store.read_entity("transfermarkt", "squads"), store.read_entity("transfermarkt", "nt_squads")],
                       ignore_index=True)
    club_names = {}
    if not squads.empty:
        for cid, nm in zip(squads["club_id"].astype(str), squads["club_name"]):
            club_names.setdefault(cid, nm)
    senior_nt = {str(v["tm_national_team_id"]): k for k, v in c["countries"].items() if v.get("tm_national_team_id")}

    empty = pd.DataFrame()
    if matches.empty:
        return empty, empty, empty, empty, competitions_table(meta)
    m = matches.copy()
    m["tm_id"] = m["tm_id"].astype(str)
    m = m[m["tm_id"].isin(tm_to_uid)]
    m["player_uid"] = m["tm_id"].map(tm_to_uid)
    m["competition_id"] = m["competition_id"].astype(str)
    m["category"] = m["competition_id"].map(lambda x: classify_competition(x, meta))
    m["competition_name"] = m["competition_id"].map(lambda x: (meta.get(x) or {}).get("name"))
    for col in ("minutes", "goals", "assists"):
        m[col] = pd.to_numeric(m[col], errors="coerce").fillna(0)
    for col in ("yellow", "red"):
        m[col] = pd.to_numeric(m[col], errors="coerce") if col in m.columns else pd.NA
    m["appeared"] = (m["minutes"] > 0).astype(int)
    m["started"] = m["is_starting"].map(lambda v: 1 if v in (True, "true", 1, "1") else (0 if v in (False, "false", 0, "0") else None)) if "is_starting" in m.columns else None
    m["club_id"] = m["club_id"].astype(str)
    is_nt = m["is_national_game"].map(lambda v: v in (True, "true", 1, "1"))

    club = m[~is_nt]
    perf = club.assign(source="transfermarkt", club_name=club["club_id"].map(club_names),
                       opponent=club["opponent_id"].astype(str).map(club_names).fillna(club["opponent_id"].astype(str)),
                       cards=club["yellow"].fillna(0) + club["red"].fillna(0) if "yellow" in club else None,
                       shots=None, xg=None, xa=None)
    perf = perf[["player_uid", "source", "date", "season", "competition_id", "competition_name", "category",
                 "club_id", "club_name", "opponent", "home_away", "minutes", "appeared", "started", "goals", "assists",
                 "yellow", "red", "cards", "shots", "xg", "xa", "position_played", "source_url", "retrieved_at"]]

    g = club.groupby(["player_uid", "season", "competition_id", "club_id"], dropna=False)
    stints = g.agg(appearances=("appeared", "sum"), squad_calls=("appeared", "size"),
                   starts=("started", lambda s: s.dropna().sum() if s.notna().any() else None),
                   minutes=("minutes", "sum"), goals=("goals", "sum"), assists=("assists", "sum"),
                   yellow_cards=("yellow", lambda s: s.sum(min_count=1)), red_cards=("red", lambda s: s.sum(min_count=1)),
                   start_date=("date", "min"), end_date=("date", "max"), source_url=("source_url", "first"),
                   retrieved_at=("retrieved_at", "max")).reset_index()
    stints["source"] = "transfermarkt"
    stints["club_name"] = stints["club_id"].map(club_names)
    stints["competition_name"] = stints["competition_id"].map(lambda x: (meta.get(x) or {}).get("name"))
    stints["category"] = stints["competition_id"].map(lambda x: classify_competition(x, meta))
    stints["country"] = stints["competition_id"].map(lambda x: (meta.get(x) or {}).get("country_id"))
    stints["competition_tier"] = stints["competition_id"].map(lambda x: 1 if str((meta.get(x) or {}).get("type_id")) == "1" else None)

    nt = m[is_nt].copy()
    nt["team"] = nt["club_id"].map(lambda x: senior_nt.get(x) or club_names.get(x) or x)
    nt["level"] = [("senior" if cid in senior_nt and cat != "seleccion_juvenil" else "youth_or_other")
                   for cid, cat in zip(nt["club_id"], nt["category"])]
    nt = nt.assign(source="transfermarkt", competition=nt["competition_name"], tournament=nt["competition_id"],
                   opponent=nt["opponent_id"].astype(str).map(club_names).fillna(nt["opponent_id"].astype(str)), captain=None)
    cols = ["player_uid", "source", "team", "level", "competition", "tournament", "date", "season", "opponent",
            "minutes", "appeared", "started", "goals", "assists", "captain", "source_url", "retrieved_at"]
    senior = nt[nt["level"] == "senior"][cols]
    youth = nt[nt["level"] != "senior"][cols]
    return stints, perf, senior, youth, competitions_table(meta)


def competitions_table(meta: dict) -> pd.DataFrame:
    rows = [{"competition_id": k, "name": v.get("name"), "country": v.get("country_id"),
             "confederation": v.get("confederation_id"), "tier": 1 if str(v.get("type_id")) == "1" else None,
             "type": v.get("type_id"), "category": classify_competition(k, meta), "source": "transfermarkt",
             "source_url": v.get("source_url")} for k, v in meta.items()]
    return pd.DataFrame(rows)


def build_fbref_stints(players: pd.DataFrame) -> pd.DataFrame:
    fb = store.read_entity("fbref", "season_stats")
    ident = store.read_table("player_identity")
    if fb.empty or players.empty:
        return pd.DataFrame()
    fb_to_uid = dict(zip(players["fbref_id"].astype(str), players["player_uid"]))
    if not ident.empty:
        for _, r in ident[ident["source"] == "fbref_name"].iterrows():
            fb_to_uid.setdefault("name:" + str(r["source_id"]), r["player_uid"])
    keys = fb["player_fbref_id"].astype(str) if "player_fbref_id" in fb.columns else pd.Series([""] * len(fb))
    fb["player_uid"] = [fb_to_uid.get(k) or fb_to_uid.get("name:" + norm_name(n)) for k, n in zip(keys, fb["player"])]
    fb = fb[fb["player_uid"].notna()]
    out = fb.rename(columns={"team": "club_name", "competition": "competition_id", "mp": "appearances",
                             "crdy": "yellow_cards", "crdr": "red_cards"})
    out["competition_name"] = out["competition_id"]
    keep = [c for c in ["player_uid", "source", "club_name", "competition_id", "competition_name", "season",
                        "appearances", "starts", "minutes", "goals", "assists", "yellow_cards", "red_cards",
                        "pk", "pkatt", "xg", "xag", "pos", "competition_type", "source_url", "retrieved_at",
                        "raw_ref", "method"] if c in out.columns]
    return out[keep]


def build_transfers(players: pd.DataFrame) -> pd.DataFrame:
    t = store.read_entity("transfermarkt", "transfers")
    if t.empty or players.empty:
        return pd.DataFrame()
    tm_to_uid = dict(zip(players["tm_id"].astype(str), players["player_uid"]))
    t["player_uid"] = t["tm_id"].astype(str).map(tm_to_uid)
    return t[t["player_uid"].notna()]


def caps_conflicts(players: pd.DataFrame, senior: pd.DataFrame) -> list[dict]:
    """Caps de perfil TM vs. partidos de seleccion mayor con minutos (TM) vs. NFT."""
    out = []
    nft = store.read_entity("nft", "caps")
    nft_caps = dict(zip(nft["nft_id"].astype(str), nft["caps_total"])) if not nft.empty else {}
    cnt = senior[senior["appeared"] == 1].groupby("player_uid").size().to_dict() if not senior.empty else {}
    for _, p in players.iterrows():
        prof = p.get("caps_tm_profile")
        vals = {"transfermarkt_profile": prof, "transfermarkt_matches": cnt.get(p["player_uid"]),
                "nft": nft_caps.get(str(p.get("nft_id")))}
        vals = {k: int(v) for k, v in vals.items() if v is not None and not (isinstance(v, float) and pd.isna(v))}
        ks = list(vals)
        for i in range(len(ks)):
            for j in range(i + 1, len(ks)):
                a, b = ks[i], ks[j]
                if abs(vals[a] - vals[b]) > 2:
                    out.append({"player_uid": p["player_uid"], "field": "caps", "source_a": a, "value_a": vals[a],
                                "source_b": b, "value_b": vals[b], "resolution": "transfermarkt_profile", "reviewed": False})
    return out


def run() -> dict:
    cands = collect_candidates()
    log.info(f"candidatos crudos: {len(cands)}")
    players, ident, conflicts, review, seeds = build_players(cands)
    store.write_table("player_identity", ident)
    stints, perf, senior, youth, comps = build_career(players)
    fb = build_fbref_stints(players)
    career = pd.concat([stints, fb], ignore_index=True) if not fb.empty else stints
    # debut = primer partido con minutos en competicion oficial de club (no amistoso)
    if not perf.empty:
        off = perf[(perf["appeared"] == 1) & (perf["category"] != "amistoso_club")]
        debut = off.groupby("player_uid")["date"].min()
        players["debut_date"] = players["player_uid"].map(debut)
        players["is_active"] = players.apply(
            lambda r: (r["retirement_date"] is None or pd.isna(r["retirement_date"])) if r.get("tm_id") else None, axis=1)
    conflicts = pd.concat([conflicts, pd.DataFrame(caps_conflicts(players, senior))], ignore_index=True)
    included = players[players["inclusion_status"] == "included"]
    excluded = players[players["inclusion_status"] != "included"]
    tables = {"players_all": players, "players": included, "excluded_players": excluded,
              "career_stints": career, "match_performance": perf, "national_team_caps": senior,
              "youth_caps": youth, "competitions": comps, "transfers": build_transfers(players),
              "conflicts": conflicts, "review_queue": review, "seed_candidates": seeds}
    for name, df in tables.items():
        store.write_table(name, df if df is not None else pd.DataFrame())
        log.info(f"{name}: {0 if df is None else len(df)} filas")
    return tables
