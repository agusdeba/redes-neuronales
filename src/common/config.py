"""Carga de configuracion YAML + .env, y hash de configuracion para source_runs."""
from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
DATA = Path(os.environ.get("RN_DATA_DIR") or ROOT / "data")
RAW = DATA / "raw"
INTERIM = DATA / "interim"
PROCESSED = DATA / "processed"
MANIFESTS = DATA / "manifests"
MANUAL = DATA / "manual"
LOGS = Path(os.environ.get("RN_LOGS_DIR") or ROOT / "logs")
REPORTS = Path(os.environ.get("RN_REPORTS_DIR") or ROOT / "reports")

for _d in (RAW, INTERIM, PROCESSED, MANIFESTS, MANUAL, LOGS, REPORTS):
    _d.mkdir(parents=True, exist_ok=True)

try:  # opcional
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:  # pragma: no cover
    pass


@lru_cache(maxsize=None)
def load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def cohort() -> dict:
    return load_yaml("cohort.yaml")


def sources() -> dict:
    return load_yaml("sources.yaml")


def positions() -> dict:
    return load_yaml("positions.yaml")


def source_cfg(name: str) -> dict:
    s = sources()
    cfg = dict(s.get("defaults", {}))
    cfg.update(s["sources"].get(name, {}))
    cfg["user_agent"] = cfg.get("user_agent") or s.get("user_agent")
    contact = os.environ.get("CONTACT_EMAIL", "").strip()
    if contact and "contacto" in cfg["user_agent"]:
        cfg["user_agent"] = cfg["user_agent"].replace("contacto en .env CONTACT_EMAIL", contact)
    return cfg


def config_hash() -> str:
    blob = json.dumps({n: load_yaml(n) for n in ("cohort.yaml", "sources.yaml", "positions.yaml")},
                      sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def code_version() -> str:
    """Commit de git si existe (para versionar cada corrida)."""
    head = ROOT / ".git" / "HEAD"
    try:
        ref = head.read_text().strip()
        if ref.startswith("ref:"):
            p = ROOT / ".git" / ref.split(" ", 1)[1]
            if p.exists():
                return p.read_text().strip()[:12]
            packed = ROOT / ".git" / "packed-refs"
            if packed.exists():
                for line in packed.read_text().splitlines():
                    if line.endswith(ref.split(" ", 1)[1]):
                        return line.split()[0][:12]
        return ref[:12]
    except OSError:
        return "unknown"
