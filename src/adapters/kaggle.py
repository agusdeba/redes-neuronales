"""Kaggle: dataset 'davidcariboo/player-scores' (derivado de Transfermarkt; player_id = TM id).

Descarga manual o con la CLI oficial:
    kaggle datasets download -d davidcariboo/player-scores -p data/manual/kaggle/player-scores --unzip
Verificar la licencia del dataset en su pagina antes de usarlo. Se usa para validar
apariciones/minutos contra el scraping de TM y como respaldo si tmapi falla.
"""
from __future__ import annotations

import pandas as pd

from ..common import store
from ..common.config import MANUAL

DIR = MANUAL / "kaggle" / "player-scores"


def load(tm_ids: set[str] | None = None) -> dict[str, pd.DataFrame]:
    out = {}
    for name in ("players", "appearances"):
        p = DIR / f"{name}.csv"
        if not p.exists():
            continue
        df = pd.read_csv(p, low_memory=False)
        if tm_ids is not None and "player_id" in df.columns:
            df = df[df["player_id"].astype(str).isin(tm_ids)]
        df["source"] = "kaggle"
        df["source_url"] = "https://www.kaggle.com/datasets/davidcariboo/player-scores"
        df["raw_ref"] = str(p)
        out[name] = df
    for name, df in out.items():
        store.write_item("kaggle", name, "player-scores", df.to_dict("records"))
    return out
