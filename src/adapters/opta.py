"""Opta / Stats Perform: PENDIENTE DE LICENCIA.

Opta es una fuente comercial. Sin credenciales no hay acceso legal a sus datos y este
proyecto NO scrapea TheAnalyst, widgets embebidos ni endpoints propietarios.
Ver docs/OPTA_ACCESO.md para las vias legales de obtener acceso (licencia academica,
contacto comercial) y las alternativas (StatsBomb Open Data, API-Football).

Cuando haya credenciales (OPTA_API_KEY / OPTA_OUTLET_KEY en .env) se implementa el
adaptador contra la API oficial que indique el contrato (Opta SDAPI).
"""
from __future__ import annotations

import os


class OptaAdapter:
    source = "opta"

    def __init__(self, **_):
        if not os.environ.get("OPTA_API_KEY") and not os.environ.get("OPTA_OUTLET_KEY"):
            raise RuntimeError("Opta: pendiente de licencia. No hay credenciales en .env (ver docs/OPTA_ACCESO.md).")
        raise NotImplementedError("Opta: implementar segun el contrato/API entregados por Stats Perform.")
