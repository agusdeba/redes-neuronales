"""ESPN: endpoints JSON publicos no documentados (site.api.espn.com). Desactivado por defecto.

Uso: contraste de fichas y estadisticas recientes cuando hay espn_id (Wikidata P3681).
Endpoint documentado por la comunidad, sin garantia de estabilidad ni licencia de reuso:
    https://site.web.api.espn.com/apis/common/v3/sports/soccer/athletes/{id}
"""
from __future__ import annotations

from ..common import store
from ..common.http import PoliteClient

ATHLETE = "https://site.web.api.espn.com/apis/common/v3/sports/soccer/athletes/{id}"


class ESPNAdapter:
    source = "espn"

    def __init__(self, refresh=False, offline=False):
        self.http = PoliteClient(self.source, refresh=refresh, offline=offline)

    def athlete(self, espn_id: str, qid: str | None = None):
        r = self.http.get(ATHLETE.format(id=espn_id))
        a = (r.json().get("athlete") or {}) if r.ok else {}
        rec = {"espn_id": espn_id, "qid": qid, "name": a.get("displayName"), "dob": (a.get("dateOfBirth") or "")[:10] or None,
               "position": (a.get("position") or {}).get("name"), "citizenship": a.get("citizenship"),
               **r.provenance()}
        store.write_item(self.source, "athlete", espn_id, [rec])
        return rec
