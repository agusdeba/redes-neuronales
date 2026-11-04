"""Orquestacion de semillas y descargas por fuente, con reanudacion por item (manifest)."""
from __future__ import annotations

import pandas as pd

from ..common import store
from ..common.config import cohort, source_cfg
from ..common.http import SourceBlocked, SourceDown, manifest
from ..common.logs import get_logger
from . import normalize

log = get_logger("pipeline.download")


def _guard(source, fn, *a, **kw):
    """Ejecuta una fuente; si se bloquea o cae, lo registra y sigue con las demas."""
    try:
        return fn(*a, **kw)
    except SourceBlocked as e:
        log.error(f"[{source}] BLOQUEADA (no se evade): {e}")
    except SourceDown as e:
        log.error(f"[{source}] circuit breaker abierto: {e}")
    except RuntimeError as e:
        log.error(f"[{source}] {e}")
    return None


def seed(sources: list[str], countries: list[str], born_from: int, born_to: int, limit=None, refresh=False,
         season_from=None, season_to=None, limit_clubs=None):
    c = cohort()
    sf = season_from or c["league_seed_seasons"]["from"]
    st = season_to or c["league_seed_seasons"]["to"]
    if "wikidata" in sources:
        from ..adapters.wikidata import WikidataAdapter
        _guard("wikidata", WikidataAdapter(refresh=refresh).seed, countries, born_from, born_to, limit)
    if "wikipedia" in sources:
        from ..adapters.wikipedia import WikipediaAdapter
        _guard("wikipedia", WikipediaAdapter(refresh=refresh).discover, countries)
    if "tm_leagues" in sources:
        from ..adapters.transfermarkt import TransfermarktAdapter
        _guard("transfermarkt", TransfermarktAdapter(refresh=refresh).seed_leagues, countries, sf, st, limit_clubs)
    if "tm_national" in sources:
        from ..adapters.transfermarkt import TransfermarktAdapter
        _guard("transfermarkt", TransfermarktAdapter(refresh=refresh).seed_national_teams, countries, sf, st)
    if "fbref" in sources:
        from ..adapters.fbref import FBrefAdapter
        _guard("fbref", FBrefAdapter(refresh=refresh).download, None, limit)


def candidate_targets(countries, born_from, born_to) -> pd.DataFrame:
    """Clusters de la cohorte que merecen descarga de carrera: excluye solo a los que TODA
    la evidencia disponible marca como arquero/defensor/mediocampista puro."""
    cands = normalize.collect_candidates()
    players, *_ = normalize.build_players(cands)
    if players.empty:
        return players
    players = players[players["nationality"].isin(countries) & players["birth_year"].between(born_from, born_to)]
    return players[players["inclusion_status"].isin(["included", "review", "unknown"])]


def careers(countries, born_from, born_to, limit=None, refresh=False, with_secondary=True):
    """Descarga la carrera completa (TM) de cada candidato; resuelve tm_id por nombre si falta.
    Luego contrasta caps (NFT) y carrera (WorldFootball) cuando hay ID en Wikidata."""
    from ..adapters.transfermarkt import TransfermarktAdapter
    m = manifest()
    tm = TransfermarktAdapter(refresh=refresh)
    todo = candidate_targets(countries, born_from, born_to)
    if limit:
        todo = todo.sort_values(["nationality", "birth_year", "player_uid"]).head(limit)
    log.info(f"jugadores a descargar: {len(todo)}")
    for _, p in todo.iterrows():
        uid = p["player_uid"]
        if m.task_status("tm_career", uid) in ("done", "no_match", "ambiguous") and not refresh:
            continue
        try:
            tm_id = p.get("tm_id")
            if not tm_id or pd.isna(tm_id):
                res = tm.resolve(p["canonical_name"], p.get("birth_year"), p.get("dob") if p.get("dob_confidence") == "exact" else None)
                store.write_item("transfermarkt", "resolution", uid, [{"player_uid": uid, "name": p["canonical_name"], **res}])
                if res["status"] != "mapped":
                    m.set_task("tm_career", uid, res["status"], str(res.get("candidates")))
                    continue
                tm_id = res["tm_id"]
            out = tm.fetch_player(str(tm_id))
            m.set_task("tm_career", uid, "done", f"tm={tm_id} partidos={out['n_matches']}")
            log.info(f"{p['canonical_name']} ({p['nationality']} {p['birth_year']}) tm={tm_id} partidos={out['n_matches']}")
        except (SourceBlocked, SourceDown) as e:
            log.error(f"transfermarkt detenido: {e}")
            break
        except Exception as e:  # noqa: BLE001 - se registra y se sigue con el proximo
            m.set_task("tm_career", uid, "error", repr(e))
            log.error(f"error {p['canonical_name']}: {e!r}")

    if not with_secondary:
        return
    if source_cfg("nft").get("enabled"):
        from ..adapters.nft import NFTAdapter
        nft = NFTAdapter(refresh=refresh)
        for _, p in todo[todo["nft_id"].notna()].iterrows():
            if m.task_status("nft", p["player_uid"]) == "done" and not refresh:
                continue
            r = _guard("nft", nft.fetch, str(p["nft_id"]), p.get("qid"))
            if r is None and m.source_state("nft")["state"] != "ok":
                break
            m.set_task("nft", p["player_uid"], "done" if r else "error")
    if source_cfg("worldfootball").get("enabled"):
        from ..adapters.worldfootball import WorldFootballAdapter
        wf = WorldFootballAdapter(refresh=refresh)
        for _, p in todo[todo["worldfootball_id"].notna()].iterrows():
            if m.task_status("worldfootball", p["player_uid"]) == "done" and not refresh:
                continue
            r = _guard("worldfootball", wf.fetch, str(p["worldfootball_id"]), p.get("qid"))
            if r is None and m.source_state("worldfootball")["state"] != "ok":
                break
            m.set_task("worldfootball", p["player_uid"], "done" if r is not None else "error")


def extras(sources: list[str], refresh=False):
    if "statsbomb" in sources:
        from ..adapters.statsbomb import StatsBombAdapter
        _guard("statsbomb", StatsBombAdapter(refresh=refresh).download)
    if "rsssf" in sources:
        from ..adapters.rsssf import RSSSFAdapter
        _guard("rsssf", RSSSFAdapter(refresh=refresh).download)
    if "kaggle" in sources:
        from ..adapters import kaggle
        kaggle.load()
