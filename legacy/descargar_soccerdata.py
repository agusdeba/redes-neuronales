#!/usr/bin/env python3
"""Descarga de FBref via soccerdata: "Player Standard Stats" de una competicion.

  python descargar_soccerdata.py --league "POR-Primeira" --start 2000 --end 2025 \
      --folder portugal --prefix fbref_portugal --out portugal_2000_2026.csv
  python descargar_soccerdata.py --league "INT-World Cup" --start 1994 --end 2026 \
      --step 4 --single-year --folder world_cup --prefix fbref_worldcup --out world_cup_1994_2026.csv
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
import soccerdata as sd

BASE = Path(__file__).resolve().parent

PATCH_LEAGUES = ["ARG-Primera", "BRA-Serie A", "COL-Primera", "ECU-Serie A",
                 "URU-Primera", "POR-Primeira"]

# Replicamos el hack usado en descargar_jugadores_sudamerica.py
try:
    _original_available = sd.FBref.available_leagues

    @classmethod
    def _ligas_forzadas(cls):
        current = list(_original_available())
        for extra in PATCH_LEAGUES:
            if extra not in current:
                current.append(extra)
        return current

    sd.FBref.available_leagues = _ligas_forzadas
except Exception:
    pass

FLAT_COLS = None
COL_MAP = {
    ("league", ""): "league",
    ("season", ""): "season",
    ("team", ""): "team",
    ("player", ""): "player",
    ("nation", ""): "nation",
    ("pos", ""): "pos",
    ("age", ""): "age",
    ("born", ""): "born",
    ("Club", ""): "club",
    ("Playing Time", "born"): "born",
    ("Playing Time", "MP"): "mp",
    ("Playing Time", "Starts"): "starts",
    ("Playing Time", "Min"): "minutes",
    ("Playing Time", "90s"): "nineties",
    ("Performance", "Gls"): "goals",
    ("Performance", "Ast"): "assists",
    ("Performance", "G+A"): "g_plus_a",
    ("Performance", "G-PK"): "g_minus_pk",
    ("Performance", "PK"): "pk",
    ("Performance", "PKatt"): "pkatt",
    ("Performance", "CrdY"): "crdy",
    ("Performance", "CrdR"): "crdr",
    ("Per 90 Minutes", "Gls"): "goals_90",
    ("Per 90 Minutes", "Ast"): "assists_90",
    ("Per 90 Minutes", "G+A"): "g_plus_a_90",
    ("Per 90 Minutes", "G-PK"): "g_minus_pk_90",
    ("Per 90 Minutes", "G+A-PK"): "g_plus_a_minus_pk_90",
}


def flatten_columns(columns):
    names = []
    for c in columns:
        key = tuple(c) if isinstance(c, tuple) else (str(c), "")
        names.append(COL_MAP.get(key, f"col_{len(names)}"))
    return names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", required=True)
    ap.add_argument("--start", type=int, required=True)
    ap.add_argument("--end", type=int, required=True)
    ap.add_argument("--step", type=int, default=1)
    ap.add_argument("--single-year", action="store_true",
                    help="Usar temporadas de un solo anio (ej. World Cup) en vez de xxyy.")
    ap.add_argument("--multiyear-code", action="store_true",
                    help="Codigo de temporada de 4 cifras xxyy (ej. Big5).")
    ap.add_argument("--folder", required=True)
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    FOLDER = BASE / args.folder
    FOLDER.mkdir(parents=True, exist_ok=True)

    years = list(range(args.start, args.end + 1, args.step))
    if args.single_year:
        seasons = [str(y) for y in years]
    elif args.multiyear_code:
        seasons = [f"{y % 100:02d}{(y + 1) % 100:02d}" for y in years]
    else:
        seasons = [str(y) for y in years]
    if args.limit:
        seasons = seasons[: args.limit]
    print(f"League: {args.league} | {years[0]}..{years[-1]} | {len(seasons)} paginas -> {seasons}")

    fbref = sd.FBref(leagues=[args.league], seasons=seasons)
    stats = fbref.read_player_season_stats(stat_type="standard")
    df = stats.reset_index()
    df.columns = flatten_columns(df.columns)
    df["season"] = df["season"].astype(str).str.zfill(4)
    df.to_csv(FOLDER / args.out, index=False)

    print(f"Total: {len(df)} filas -> {FOLDER / args.out}")
    print(f"Columnas: {df.columns.tolist()}")
    print(df.groupby(["league", "season"], sort=True).size().to_string())

    return 0


if __name__ == "__main__":
    sys.exit(main())