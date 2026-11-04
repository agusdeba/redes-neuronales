"""Wikidata: semilla de la cohorte (SPARQL oficial, CC0) + IDs cruzados + clubes/selecciones.

Una consulta por pais y anio de nacimiento para no superar el timeout de 60 s.
No se filtra por posicion en la consulta: se trae la posicion y el filtro se aplica
despues (muchos jugadores menores no tienen P413 cargado).
"""
from __future__ import annotations

from ..common import store
from ..common.config import cohort
from ..common.http import PoliteClient, manifest
from ..common.logs import get_logger

ENDPOINT = "https://query.wikidata.org/sparql"
FOOTBALLER = "Q937857"

PROPS = {  # propiedad -> columna
    "P2446": "tm_id",
    "P5750": "fbref_id",
    "P2574": "nft_id",
    "P2020": "worldfootball_id",
    "P2369": "soccerway_id",
    "P3681": "espn_id",
}

PLAYERS_Q = """
SELECT ?p ?pLabel ?dob ?prec ?pos ?posLabel ?birthName ?alias
       %(prop_vars)s ?es ?pt ?en WHERE {
  ?p wdt:P106 wd:%(footballer)s ;
     wdt:P27 wd:%(country)s ;
     p:P569/psv:P569 [ wikibase:timeValue ?dob ; wikibase:timePrecision ?prec ] .
  FILTER(?dob >= "%(y)d-01-01T00:00:00Z"^^xsd:dateTime && ?dob < "%(y1)d-01-01T00:00:00Z"^^xsd:dateTime)
  OPTIONAL { ?p wdt:P413 ?pos }
  OPTIONAL { ?p wdt:P1477 ?birthName }
  OPTIONAL { ?p skos:altLabel ?alias . FILTER(LANG(?alias) IN ("es","pt","en")) }
  %(prop_opts)s
  OPTIONAL { ?es schema:about ?p ; schema:isPartOf <https://es.wikipedia.org/> }
  OPTIONAL { ?pt schema:about ?p ; schema:isPartOf <https://pt.wikipedia.org/> }
  OPTIONAL { ?en schema:about ?p ; schema:isPartOf <https://en.wikipedia.org/> }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "es,pt,en". }
}
"""

TEAMS_Q = """
SELECT ?p ?team ?teamLabel ?isNT ?start ?end ?apps ?goals WHERE {
  ?p wdt:P106 wd:%(footballer)s ;
     wdt:P27 wd:%(country)s ;
     wdt:P569 ?dob .
  FILTER(?dob >= "%(y)d-01-01T00:00:00Z"^^xsd:dateTime && ?dob < "%(y1)d-01-01T00:00:00Z"^^xsd:dateTime)
  ?p p:P54 ?st . ?st ps:P54 ?team .
  OPTIONAL { ?st pq:P580 ?start } OPTIONAL { ?st pq:P582 ?end }
  OPTIONAL { ?st pq:P1350 ?apps } OPTIONAL { ?st pq:P1351 ?goals }
  BIND(EXISTS { ?team wdt:P31/wdt:P279* wd:Q6979593 } AS ?isNT)
  SERVICE wikibase:label { bd:serviceParam wikibase:language "es,en". }
}
"""


def _val(b, k):
    v = b.get(k)
    return v["value"] if v else None


def _qid(uri):
    return uri.rsplit("/", 1)[-1] if uri else None


class WikidataAdapter:
    source = "wikidata"

    def __init__(self, refresh=False, offline=False):
        self.http = PoliteClient(self.source, refresh=refresh, offline=offline)
        self.http.session.headers["Accept"] = "application/sparql-results+json"
        self.log = get_logger("adapter.wikidata")

    def sparql(self, query: str):
        r = self.http.get(ENDPOINT, method="POST", data={"query": query, "format": "json"})
        if not r.ok:
            raise RuntimeError(f"SPARQL HTTP {r.status}")
        return r, r.json()["results"]["bindings"]

    def players_query(self, country_qid: str, year: int) -> str:
        prop_vars = " ".join(f"?{c}" for c in PROPS.values())
        prop_opts = "\n  ".join(f"OPTIONAL {{ ?p wdt:{p} ?{c} }}" for p, c in PROPS.items())
        return PLAYERS_Q % dict(prop_vars=prop_vars, prop_opts=prop_opts, footballer=FOOTBALLER,
                                country=country_qid, y=year, y1=year + 1)

    @staticmethod
    def parse_players(bindings, prov: dict, country: str) -> list[dict]:
        """Agrupa filas SPARQL (una por combinacion de opcionales) en 1 registro por QID."""
        out: dict[str, dict] = {}
        for b in bindings:
            qid = _qid(_val(b, "p"))
            if not qid:
                continue
            rec = out.setdefault(qid, {
                "qid": qid, "name": _val(b, "pLabel"), "dob_raw": _val(b, "dob"),
                "dob_precision": int(_val(b, "prec") or 0), "nationality": country,
                "positions": set(), "aliases": set(), "birth_name": _val(b, "birthName"),
                **{c: None for c in PROPS.values()},
                "wiki_es": _val(b, "es"), "wiki_pt": _val(b, "pt"), "wiki_en": _val(b, "en"), **prov})
            if _val(b, "posLabel"):
                rec["positions"].add(_val(b, "posLabel"))
            if _val(b, "alias"):
                rec["aliases"].add(_val(b, "alias"))
            for c in PROPS.values():
                if _val(b, c) and not rec[c]:
                    rec[c] = _val(b, c)
        res = []
        for rec in out.values():
            dob = (rec.pop("dob_raw") or "")[:10]
            prec = rec["dob_precision"]
            rec["dob"] = dob if prec >= 11 else None
            rec["birth_year"] = int(dob[:4]) if dob[:4].isdigit() else None
            rec["dob_confidence"] = "exact" if prec >= 11 else "year_only"
            rec["positions"] = sorted(rec["positions"])
            rec["aliases"] = sorted(rec["aliases"])
            res.append(rec)
        return res

    def seed(self, countries: list[str], year_from: int, year_to: int, limit: int | None = None) -> int:
        cfg = cohort()["countries"]
        m = manifest()
        n = 0
        for c in countries:
            for y in range(year_from, year_to + 1):
                item = f"{c}_{y}"
                if m.task_status("wikidata_seed", item) == "done" and not self.http.refresh:
                    continue
                r, b = self.sparql(self.players_query(cfg[c]["wikidata_qid"], y))
                recs = self.parse_players(b, r.provenance(), c)
                if limit:
                    recs = recs[:limit]
                store.write_item(self.source, "players", item, recs)
                # clubes y selecciones (P54) con apps/goles si estan cargados
                q = TEAMS_Q % dict(footballer=FOOTBALLER, country=cfg[c]["wikidata_qid"], y=y, y1=y + 1)
                r2, b2 = self.sparql(q)
                keep = {x["qid"] for x in recs}
                teams = [{"qid": _qid(_val(t, "p")), "team_qid": _qid(_val(t, "team")),
                          "team_name": _val(t, "teamLabel"), "is_national_team": _val(t, "isNT") == "true",
                          "start": (_val(t, "start") or "")[:10] or None, "end": (_val(t, "end") or "")[:10] or None,
                          "apps": _val(t, "apps"), "goals": _val(t, "goals"), **r2.provenance()}
                         for t in b2 if _qid(_val(t, "p")) in keep]
                store.write_item(self.source, "teams", item, teams)
                m.set_task("wikidata_seed", item, "done", f"{len(recs)} jugadores")
                self.log.info(f"{item}: {len(recs)} jugadores, {len(teams)} pasos por equipos")
                n += len(recs)
        return n
