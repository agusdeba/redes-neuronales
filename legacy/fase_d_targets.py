#!/usr/bin/env python3
"""Fase D: targets de carrera (Transfermarkt) sobre la cohorte madura.

Genera csv/ml/jugadores_target_ml.csv a partir de:
  - csv/ml/jugadores_sudamericanos_etl.csv  (Fase B, features, 783 filas)
  - csv/ml/tm_summary.csv                   (Fase C, caps + minutos TM)

Los targets solo se calculan para la cohorte madura (cohort_mature==1) con
tm_id resuelto; los demas quedan como NaN (se excluyen de entrenamiento).

Definiciones:
  min_elite_puente = tm_min_elite_puente (1as divisiones europeas, toda la carrera)
  target_standard  = (caps >= 15) OR (min_elite_puente >= 3500)
  target_elite     = (caps >= 30) OR (min_elite_puente >= 8000)

  python fase_d_targets.py
"""

import os
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.abspath(__file__))
BEST = os.path.join(ROOT, "csv", "ml")
ETL_CSV = os.path.join(BEST, "jugadores_sudamericanos_etl.csv")
SUMMARY_CSV = os.path.join(BEST, "tm_summary.csv")
OUT_CSV = os.path.join(BEST, "jugadores_target_ml.csv")

TM_COLS = ["caps", "nt_goals", "tm_min_elite", "tm_min_puente",
           "tm_min_elite_puente", "tm_min_continental", "tm_min_seleccion", "tm_n_games"]

TARGET_STANDARD_MIN = 3500
TARGET_ELITE_MIN = 8000
CAPS_STANDARD = 15
CAPS_ELITE = 30


def main():
    etl = pd.read_csv(ETL_CSV, dtype={"player_id_global": str})
    s = pd.read_csv(SUMMARY_CSV, dtype=str).fillna("")

    # --- join 1:1
    d = etl.merge(s, on="player_id_global", how="left", suffixes=("", "_sum"))
    assert len(d) == len(etl), "join modifico filas"
    assert d["player_id_global"].is_unique, "ids duplicados"

    # --- sanity del join
    d["tm_id"] = d["tm_id"].fillna("")
    colunas = d["_merge"] if "_merge" in d.columns else None
    n_join = int((d["tm_id"] != "").sum())
    print(f"[FASE D] join ETL<->summary OK: {len(d)} filas | con tm_id: {n_join}")

    # conversiones numericas verbose
    for c in TM_COLS:
        d[c] = pd.to_numeric(d[c], errors="coerce").fillna(0)
    d["tm_id"] = d["tm_id"].astype(str)
    d["tm_resuelto"] = (d["tm_id"] != "").astype(int)

    # --- targets solo cohorte madura + tm resuelto
    d["caps_tm"] = d["caps"]
    d["nt_goals_tm"] = d["nt_goals"]
    d["min_elite"] = d["tm_min_elite"]
    d["min_puente"] = d["tm_min_puente"]
    d["min_elite_puente"] = d["tm_min_elite_puente"]
    d["min_continental"] = d["tm_min_continental"]
    d["min_seleccion"] = d["tm_min_seleccion"]
    d["n_partidos_tm"] = d["tm_n_games"]

    # sanity: sin tm_id no puede haber minutos/caps
    bad = d[(d["tm_resuelto"] == 0) & (
        (d[["min_elite_puente", "min_continental", "min_seleccion", "caps_tm"]].sum(axis=1) > 0))]
    print(f"[FASE D] sanity: sin tm_id pero con minutos/caps > 0: {len(bad)}")

    mature = d["cohort_mature"] == 1
    resolved = d["tm_resuelto"] == 1
    d["target_standard"] = pd.NA
    d["target_elite"] = pd.NA
    mask = mature & resolved
    d.loc[mask, "target_standard"] = (
        (d.loc[mask, "caps_tm"] >= CAPS_STANDARD) | (d.loc[mask, "min_elite_puente"] >= TARGET_STANDARD_MIN)
    ).astype(int)
    d.loc[mask, "target_elite"] = (
        (d.loc[mask, "caps_tm"] >= CAPS_ELITE) | (d.loc[mask, "min_elite_puente"] >= TARGET_ELITE_MIN)
    ).astype(int)

    # sanity: todo elite es standard
    elite_set = d.loc[d["target_elite"] == 1, "target_standard"]
    print(f"[FASE D] sanity: elite=1 siempre con standard=1: {bool((elite_set == 1).all())}")

    cols_out = list(etl.columns) + ["tm_resuelto", "caps_tm", "nt_goals_tm",
                                    "min_elite", "min_puente", "min_elite_puente",
                                    "min_continental", "min_seleccion", "n_partidos_tm",
                                    "target_standard", "target_elite"]
    d[cols_out].to_csv(OUT_CSV, index=False, encoding="utf-8")

    # ------------------------------------------------ reporte embudo
    total = len(d)
    mat = int(mature.sum())
    res = int((mature & resolved).sum())
    std = int((d["target_standard"] == 1).sum())
    el = int((d["target_elite"] == 1).sum())
    print()
    print("================= EMBUDO FINAL (Fase D) =================")
    print(f"  Dataset Fase B total                    : {total}")
    print(f"  Cohorte madura (born 1995-2000)         : {mat}")
    print(f"    con tm_id resuelto                    : {res}")
    print(f"    sin resolver (excluidos de training)  : {mat - res}")
    print(f"  target_standard = 1                     : {std} ({std/res*100:.1f}% de {res})")
    print(f"  target_elite    = 1                     : {el} ({el/res*100:.1f}% de {res})")
    print("  -------------------------------------------------------")
    print("  distribucion target_standard:")
    print(d.loc[mask, "target_standard"].value_counts(dropna=False).reindex([1, 0]).fillna(0).astype(int).to_string())
    print("  distribucion target_elite:")
    print(d.loc[mask, "target_elite"].value_counts(dropna=False).reindex([1, 0]).fillna(0).astype(int).to_string())

    print("\n  target_standard por nacion (rate):")
    g = d[mask].groupby("nation")["target_standard"]
    fr = (g.sum() / g.count() * 100).round(1).sort_values(ascending=False)
    print(fr.to_string())

    print("\n  target_elite por anio de nacimiento (rate):")
    g = d[mask].groupby(d["born"])["target_elite"]
    fr = (g.sum() / g.count() * 100).round(1)
    print(fr.to_string())

    print(f"\n  guardado -> {OUT_CSV} | columnas: {len(cols_out)} | filas: {len(d)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())