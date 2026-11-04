"""Clasificacion de posicion y regla de inclusion.

Decision del usuario (2026-11-04):
  - Cualquier jugador cuya posicion PRIMARIA sea de ataque entra.
  - Si juega de delantero pero NO es su primera posicion => cola de revision; el
    usuario decide en data/manual/position_decisions.csv (include / exclude).
  - Sin evidencia de ataque => excluido (se lista igual, con motivo).
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field

from ..common.config import MANUAL, positions
from ..common.textnorm import norm_label

GROUPS = ("attack", "ambiguous", "midfield", "defense", "goalkeeper")


def classify_label(source: str, label: str | None) -> str | None:
    """Etiqueta de una fuente -> grupo (o None si no se reconoce)."""
    if not label:
        return None
    cfg = positions().get(source, {})
    lab = norm_label(label)
    if source == "fbref":
        tok = str(label).upper().replace("-", ",").split(",")[0].strip()
        return cfg["tokens"].get(tok)
    if source == "transfermarkt" and " - " in label:  # "Attack - Centre-Forward"
        lab = norm_label(label.split(" - ", 1)[1])
    for g in GROUPS:
        for v in cfg.get(g, []):
            if lab == norm_label(v):
                return g
    for g in GROUPS:  # coincidencia parcial como respaldo ("left winger" dentro de un texto)
        for v in cfg.get(g, []):
            if norm_label(v) in lab:
                return g
    return None


def fbref_groups(pos: str | None) -> tuple[str | None, list[str]]:
    """'MF,FW' -> ('midfield', ['attack'])"""
    if not pos or str(pos) == "nan":
        return None, []
    toks = [t.strip() for t in str(pos).upper().replace("-", ",").split(",") if t.strip()]
    g = [positions()["fbref"]["tokens"].get(t) for t in toks]
    g = [x for x in g if x]
    return (g[0] if g else None), g[1:]


@dataclass
class PositionEvidence:
    primary: dict = field(default_factory=dict)     # fuente -> grupo primario
    secondary: dict = field(default_factory=dict)   # fuente -> [grupos secundarios]
    raw: dict = field(default_factory=dict)         # fuente -> texto original
    minutes_by_group: dict = field(default_factory=dict)  # si la fuente da minutos por posicion

    def add(self, source, primary_group, secondary_groups=(), raw=None):
        if primary_group:
            self.primary.setdefault(source, primary_group)
        if secondary_groups:
            self.secondary.setdefault(source, [])
            self.secondary[source].extend(g for g in secondary_groups if g)
        if raw:
            self.raw.setdefault(source, raw)


STRONG = ("transfermarkt", "fbref")


def decide(ev: PositionEvidence) -> tuple[str, str, str]:
    """Devuelve (status, position_group, reason). status: included | review | excluded | unknown."""
    if not ev.primary and not ev.secondary:
        return "unknown", "unknown", "sin evidencia de posicion en ninguna fuente"
    strong_prim = {s: g for s, g in ev.primary.items() if s in STRONG}
    prims = strong_prim or ev.primary
    attack_prim = [s for s, g in prims.items() if g == "attack"]
    other_prim = {s: g for s, g in prims.items() if g not in ("attack", None)}
    attack_sec = [s for s, gs in ev.secondary.items() if "attack" in gs]

    # minutos por posicion mandan si existen (regla de mayoria de minutos)
    if ev.minutes_by_group:
        tot = sum(ev.minutes_by_group.values()) or 1
        share = ev.minutes_by_group.get("attack", 0) / tot
        if share >= 0.5:
            return "included", "attack", f"mayoria de minutos como delantero ({share:.0%})"

    if attack_prim and not other_prim:
        return "included", "attack", "posicion primaria de ataque en " + ",".join(sorted(attack_prim))
    if attack_prim and other_prim:
        return ("review", "attack_conflict",
                f"conflicto entre fuentes: ataque en {','.join(sorted(attack_prim))}; "
                + ", ".join(f"{s}={g}" for s, g in sorted(other_prim.items())))
    if attack_sec:
        return ("review", "attack_secondary",
                "ataque solo como posicion secundaria (" + ",".join(sorted(attack_sec)) + "); primaria: "
                + ", ".join(f"{s}={g}" for s, g in sorted(prims.items())))
    if all(g == "ambiguous" for g in prims.values()):
        return "review", "ambiguous", "posicion ambigua (" + ", ".join(f"{s}={ev.raw.get(s)}" for s in prims) + ")"
    return "excluded", sorted(set(prims.values()))[0], "sin ataque: " + ", ".join(
        f"{s}={ev.raw.get(s) or g}" for s, g in sorted(prims.items()))


def manual_decisions() -> dict[str, str]:
    """data/manual/position_decisions.csv: player_uid,decision(include|exclude),note"""
    p = MANUAL / "position_decisions.csv"
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as fh:
        return {r["player_uid"]: r["decision"].strip().lower() for r in csv.DictReader(fh) if r.get("player_uid")}
