"""Persistencia: interim por item (idempotente) y tablas canonicas en Parquet + CSV."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pandas as pd

from .config import INTERIM, PROCESSED


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(s))[:150]


def write_item(source: str, entity: str, item: str, records: list[dict]) -> Path:
    """Sobrescribe el archivo del item => volver a correr no duplica."""
    d = INTERIM / source / entity
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{_safe(item)}.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(records, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(tmp, p)
    return p


def has_item(source: str, entity: str, item: str) -> bool:
    return (INTERIM / source / entity / f"{_safe(item)}.json").exists()


def read_item(source: str, entity: str, item: str) -> list[dict]:
    p = INTERIM / source / entity / f"{_safe(item)}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def read_entity(source: str, entity: str) -> pd.DataFrame:
    d = INTERIM / source / entity
    if not d.exists():
        return pd.DataFrame()
    rows: list[dict] = []
    for p in sorted(d.glob("*.json")):
        try:
            rows.extend(json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return pd.DataFrame(rows)


def write_table(name: str, df: pd.DataFrame, out_dir: Path | None = None) -> tuple[Path, Path]:
    out = Path(out_dir or PROCESSED)
    out.mkdir(parents=True, exist_ok=True)
    pq, csv = out / f"{name}.parquet", out / f"{name}.csv"
    df = df.copy()
    for c in df.columns:  # parquet no acepta columnas object con tipos mezclados
        if df[c].dtype == object:
            df[c] = df[c].map(lambda v: v if v is None or isinstance(v, str) else
                              (None if isinstance(v, float) and pd.isna(v) else str(v)))
    df.to_parquet(pq, index=False)
    df.to_csv(csv, index=False, encoding="utf-8")
    return pq, csv


def read_table(name: str, in_dir: Path | None = None) -> pd.DataFrame:
    p = Path(in_dir or PROCESSED) / f"{name}.parquet"
    return pd.read_parquet(p) if p.exists() else pd.DataFrame()
