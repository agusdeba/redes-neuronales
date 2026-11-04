#!/usr/bin/env python3
"""Descarga de FBref via soccerdata: "Player Standard Stats" de las Big 5 European Leagues Combined.

  python descargar_big5.py                   # 1995-96 a 2025-26
  python descargar_big5.py --start 1995 --end 2025

Salida:
  Big5EuropeanLeague/fbref_big5_<temporada>.csv   (un CSV por temporada)
  Big5EuropeanLeague/Big5EuropeanLeague1995_2026.csv  (archivo final unificado)
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
import soccerdata as sd

BASE = Path(__file__).resolve().parent
FOLDER = BASE / "Big5EuropeanLeague"
PREFIX = "fbref_big5"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=1995)
    parser.add_argument("--end", type=int, default=2025)
    parser.add_argument("--limit", type=int, default=0, help="Solo las primeras N temporadas (prueba).")
    args = parser.parse_args()

    FOLDER.mkdir(parents=True, exist_ok=True)
    years = list(range(args.start, args.end + 1))
    seasons = [f"{y % 100:02d}{(y + 1) % 100:02d}" for y in years]
    if args.limit:
        seasons = seasons[: args.limit]
    print(f"Seasons: {years[0]}..{years[-1]} ({len(seasons)} temporadas) -> {seasons}")

    fbref = sd.FBref(leagues=["Big 5 European Leagues Combined"], seasons=seasons)
    stats = fbref.read_player_season_stats(stat_type="standard")
    df = stats.reset_index()

    flat_cols = [
        "league", "season", "team", "player", "nation", "pos", "age", "born",
        "mp", "starts", "minutes", "nineties",
        "goals", "assists", "g_plus_a", "g_minus_pk", "pk", "pkatt", "crdy", "crdr",
        "goals_90", "assists_90", "g_plus_a_90", "g_minus_pk_90", "g_plus_a_minus_pk_90",
    ]
    if len(df.columns) != len(flat_cols):
        raise SystemExit(f"Numero de columnas inesperado: {len(df.columns)} != {len(flat_cols)}")
    df.columns = flat_cols
    df["season"] = df["season"].astype(str).str.zfill(4)

    print(f"Registros totales: {len(df)}")
    print(f"Columnas: {df.columns.tolist()}")

    for season, g in df.groupby("season", sort=True):
        code = str(season).replace("/", "-")
        path = FOLDER / f"{PREFIX}_{code}.csv"
        g.to_csv(path, index=False)
        nrow = len(g)
        nplayers = g["player"].nunique() if "player" in g else -1
        print(f"  -> {path.name}: {nrow} filas ({nplayers} jugadores)")

    final = FOLDER / "Big5EuropeanLeague1995_2026.csv"
    df.to_csv(final, index=False)
    print(f"Unificado: {final.name} ({len(df)} filas)")

    return 0


if __name__ == "__main__":
    sys.exit(main())