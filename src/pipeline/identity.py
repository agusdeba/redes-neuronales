"""Resolucion de identidad.

Anclas: Transfermarkt ID > Wikidata QID > FBref ID.
  1) Union exacta por IDs compartidos (Wikidata publica tm_id y fbref_id).
  2) Registros sin ancla fuerte (p. ej. filas FBref sin link): fuzzy WRatio >= umbral
     DENTRO de un bloque (anio de nacimiento + nacionalidad) y confirmacion obligatoria
     por un segundo campo (DOB exacta igual, o club+temporada en comun).
  3) Dos candidatos a < 5 puntos entre si, o sin confirmacion => review_queue.
Nunca se fusiona por nombre solo.

player_uid = sha1("<ancla>:<id>")[:16], deterministico.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict

from rapidfuzz import fuzz

from ..common.textnorm import norm_name

FUZZY_MIN = 92.0
MARGIN = 5.0


def make_uid(tm_id=None, qid=None, fbref_id=None, fallback=None) -> str:
    if tm_id:
        key = f"tm:{tm_id}"
    elif qid:
        key = f"wd:{qid}"
    elif fbref_id:
        key = f"fb:{fbref_id}"
    else:
        key = f"x:{fallback}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]


class UnionFind:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def cluster_records(records: list[dict]) -> dict[int, int]:
    """records: dicts con claves opcionales tm_id, qid, fbref_id. Devuelve idx -> idx raiz.
    Solo une por IDs exactos."""
    uf = UnionFind()
    for i, r in enumerate(records):
        uf.find(("r", i))
        for k in ("tm_id", "qid", "fbref_id"):
            v = r.get(k)
            if v and str(v) not in ("nan", "None", ""):
                uf.union(("r", i), (k, str(v)))
    return {i: uf.find(("r", i)) for i in range(len(records))}


def fuzzy_attach(orphan: dict, candidates: list[dict], threshold: float = FUZZY_MIN) -> dict:
    """Intenta unir un registro sin ancla a un cluster. candidates: dicts con
    uid, names (lista), birth_year, nationality, dob, club_seasons (set de (norm_club, season_start)).
    Devuelve {'status': mapped|review|new, 'uid', 'score', 'method', 'note'}."""
    by = orphan.get("birth_year")
    nat = orphan.get("nationality")
    name = norm_name(orphan.get("name"))
    block = [c for c in candidates
             if c.get("birth_year") and by and abs(int(c["birth_year"]) - int(by)) <= (1 if orphan.get("dob_confidence") == "year_only" else 0)
             and (not nat or not c.get("nationality") or nat == c.get("nationality"))]
    scored = []
    for c in block:
        s = max((fuzz.WRatio(name, norm_name(n)) for n in c.get("names", []) if n), default=0)
        if s >= threshold:
            scored.append((s, c))
    scored.sort(key=lambda x: -x[0])
    if not scored:
        return {"status": "new", "uid": None, "score": 0, "method": None, "note": "sin candidato en el bloque"}
    if len(scored) > 1 and scored[0][0] - scored[1][0] < MARGIN:
        return {"status": "review", "uid": None, "score": scored[0][0], "method": "fuzzy",
                "note": "candidatos empatados: " + ", ".join(c["uid"] for _, c in scored[:3])}
    s, c = scored[0]
    if orphan.get("dob") and c.get("dob") and orphan["dob"] == c["dob"]:
        return {"status": "mapped", "uid": c["uid"], "score": s, "method": "fuzzy+dob", "note": ""}
    oc = orphan.get("club_seasons") or set()
    if oc and c.get("club_seasons"):
        for club, season in oc:
            for c2, s2 in c["club_seasons"]:
                if season == s2 and fuzz.WRatio(club, c2) >= 85:
                    return {"status": "mapped", "uid": c["uid"], "score": s, "method": "fuzzy+club_season", "note": f"{club} {season}"}
    return {"status": "review", "uid": c["uid"], "score": s, "method": "fuzzy",
            "note": "nombre coincide pero sin segundo campo que confirme (DOB o club+temporada)"}


def build_blocks(candidates: list[dict]) -> dict:
    idx = defaultdict(list)
    for c in candidates:
        idx[(c.get("birth_year"), c.get("nationality"))].append(c)
    return idx
