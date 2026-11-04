"""Reporte de cobertura y calidad en reports/REPORTE.md (+ CSVs en reports/validation/)."""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from ..common import store
from ..common.config import REPORTS, code_version, config_hash, cohort, sources
from ..common.http import manifest


def _md(df: pd.DataFrame, max_rows=60) -> str:
    if df is None or df.empty:
        return "_(sin datos)_\n"
    d = df.head(max_rows)
    cols = [str(c) for c in d.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in d.itertuples(index=False):
        lines.append("| " + " | ".join("" if (isinstance(v, float) and pd.isna(v)) else str(v) for v in r) + " |")
    if len(df) > max_rows:
        lines.append(f"\n_... {len(df) - max_rows} filas mas en el CSV._")
    return "\n".join(lines) + "\n"


def run(val: dict | None = None) -> str:
    from . import validate
    val = val or validate.run()
    c = cohort()
    players_all = store.read_table("players_all")
    players = store.read_table("players")
    seeds = store.read_table("seed_candidates")
    conflicts = store.read_table("conflicts")
    review = store.read_table("review_queue")
    m = manifest()
    parts = [f"# Reporte de cobertura y calidad\n\nGenerado {datetime.now():%Y-%m-%d %H:%M} | codigo `{code_version()}` | config `{config_hash()}`\n",
             f"Cohorte: nacidos {c['born_from']} a {c['born_to']}, paises {', '.join(c['countries'])}, corte {c['cutoff_date']}.\n"]
    n_inc = len(players)
    st = players_all["inclusion_status"].value_counts().to_dict() if not players_all.empty else {}
    parts.append(f"## Resumen\n\n- Jugadores en la cohorte (cualquier posicion): {len(players_all)}\n"
                 f"- Incluidos (delanteros): {n_inc}\n- En revision manual: {st.get('review', 0)}\n"
                 f"- Excluidos por posicion: {st.get('excluded', 0)}\n- Sin evidencia de posicion: {st.get('unknown', 0)}\n")
    if n_inc:
        pct = lambda s: f"{100 * s.mean():.1f}%"
        perf = store.read_table("match_performance")
        parts.append("## Criterios de aceptacion\n\n"
                     f"- Paises representados: {players['nationality'].nunique()} de 7\n"
                     f"- Anios de nacimiento con jugadores: {players['birth_year'].nunique()} de 22\n"
                     f"- DOB exacta: {pct(players['dob_confidence'] == 'exact')} (meta 95%)\n"
                     f"- Con evidencia de posicion: {pct(players['position_evidence'].notna())} (meta 95%)\n"
                     f"- Con debut: {pct(players['debut_date'].notna())} (meta 90%)\n"
                     f"- Con carrera completa (TM): {pct(players['player_uid'].isin(perf['player_uid']) if not perf.empty else pd.Series([False]))} (meta 90%)\n"
                     f"- Duplicados de player_uid: {int(players['player_uid'].duplicated().sum())}\n")
    parts.append("## Cobertura por pais y anio de nacimiento\n\n" + _md(val["coverage"], 200))
    if not seeds.empty:
        s = seeds.drop_duplicates(["player_uid", "seed"])
        coh = set(players_all["player_uid"]) if not players_all.empty else set()
        s = s[s["player_uid"].isin(coh)]
        per = s.groupby("seed")["player_uid"].nunique().rename("jugadores")
        only = s.groupby("player_uid")["seed"].nunique()
        excl = s[s["player_uid"].isin(only[only == 1].index)].groupby("seed")["player_uid"].nunique().rename("exclusivos")
        parts.append("## Aporte de cada semilla (jugadores de la cohorte)\n\n" + _md(pd.concat([per, excl], axis=1).fillna(0).astype(int).reset_index()))
    parts.append("## Cola de revision (decidis vos)\n\nEditar `data/manual/position_decisions.csv` con `player_uid,decision,note` (decision = include | exclude) y volver a correr `normalize`.\n\n"
                 + _md(review, 300))
    exc = players_all[players_all["inclusion_status"].isin(["excluded", "unknown"])] if not players_all.empty else players_all
    parts.append("## Excluidos por posicion (con motivo)\n\n" + _md(exc[["player_uid", "canonical_name", "nationality", "birth_year", "position_raw", "inclusion_reason"]] if not exc.empty else exc, 300))
    parts.append("## Conflictos entre fuentes\n\n" + (_md(conflicts.groupby(["field", "source_a", "source_b"]).size().rename("n").reset_index()) if not conflicts.empty else "_(ninguno)_\n"))
    sanity = val["sanity"]
    parts.append("## Sanity checks\n\n" + (_md(sanity.groupby("check").size().rename("n").reset_index()) if not sanity.empty else "_(sin problemas)_\n"))
    parts.append("## Muestra de auditoria manual\n\n`reports/validation/audit_sample.csv` (30 jugadores estratificados por pais y decada; completar audit_ok/audit_note).\n")
    rows = []
    for name, cfg in sources()["sources"].items():
        stt = m.source_state(name)
        n_ok = m.db.execute("SELECT COUNT(*) FROM requests WHERE source=? AND status='ok'", (name,)).fetchone()[0]
        rows.append({"fuente": name, "habilitada": cfg.get("enabled"), "estado": stt["state"], "requests_ok": n_ok,
                     "licencia": cfg.get("license"), "nota": stt.get("note") or ""})
    parts.append("## Fuentes, estado y licencias\n\n" + _md(pd.DataFrame(rows), 50))
    txt = "\n".join(parts)
    (REPORTS / "REPORTE.md").write_text(txt, encoding="utf-8")
    return txt
