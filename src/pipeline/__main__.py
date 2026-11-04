"""CLI del pipeline.

  python -m src.pipeline check-config
  python -m src.pipeline seed      --sources wikidata,wikipedia,tm_leagues,tm_national,fbref --countries PAR --born-from 1990 --born-to 1990 --limit 50
  python -m src.pipeline download  --countries PAR --born-from 1990 --born-to 1990 --limit 20
  python -m src.pipeline extras    --sources statsbomb,rsssf,kaggle
  python -m src.pipeline normalize
  python -m src.pipeline features
  python -m src.pipeline targets
  python -m src.pipeline validate
  python -m src.pipeline report
  python -m src.pipeline all       (normalize -> features -> targets -> validate -> report)
  python -m src.pipeline status
  python -m src.pipeline reset-source transfermarkt
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from ..common.config import MANIFESTS, code_version, config_hash, cohort
from ..common.http import manifest
from ..common.logs import RUN_ID, get_logger

log = get_logger("pipeline")


def _countries(s):
    return [x.strip().upper() for x in s.split(",")] if s else list(cohort()["countries"])


def _record_run(cmd, args, status, started):
    m = manifest()
    m.db.execute("CREATE TABLE IF NOT EXISTS source_runs(run_id TEXT, command TEXT, started_at TEXT, finished_at TEXT, "
                 "status TEXT, args TEXT, config_hash TEXT, code_version TEXT, requests INTEGER, errors INTEGER)")
    n_req = m.db.execute("SELECT COUNT(*) FROM requests WHERE run_id=?", (RUN_ID,)).fetchone()[0]
    n_err = m.db.execute("SELECT COUNT(*) FROM requests WHERE run_id=? AND status NOT IN ('ok','not_found')", (RUN_ID,)).fetchone()[0]
    m.db.execute("INSERT INTO source_runs VALUES(?,?,?,?,?,?,?,?,?,?)",
                 (RUN_ID, cmd, started, datetime.now(timezone.utc).isoformat(), status, json.dumps(vars(args), default=str),
                  config_hash(), code_version(), n_req, n_err))
    m.db.commit()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m src.pipeline")
    ap.add_argument("command", choices=["check-config", "seed", "download", "extras", "normalize", "features", "targets",
                                        "validate", "report", "all", "status", "reset-source"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--sources", default="wikidata,wikipedia,tm_leagues,tm_national,fbref")
    ap.add_argument("--countries", default=None)
    ap.add_argument("--born-from", type=int, default=None)
    ap.add_argument("--born-to", type=int, default=None)
    ap.add_argument("--season-from", type=int, default=None)
    ap.add_argument("--season-to", type=int, default=None)
    ap.add_argument("--limit", type=int, default=None, help="limite de items (prueba)")
    ap.add_argument("--limit-clubs", type=int, default=None, help="clubes por liga/temporada (prueba)")
    ap.add_argument("--refresh", action="store_true", help="ignora la cache y vuelve a descargar")
    ap.add_argument("--no-secondary", action="store_true", help="download: solo TM, sin NFT/WorldFootball")
    a = ap.parse_args(argv)
    c = cohort()
    bf = a.born_from or int(c["born_from"][:4])
    bt = a.born_to or int(c["born_to"][:4])
    started = datetime.now(timezone.utc).isoformat()
    status = "ok"
    try:
        if a.command == "check-config":
            from .checks import check_config
            check_config()
        elif a.command == "seed":
            from . import download
            download.seed(a.sources.split(","), _countries(a.countries), bf, bt, a.limit, a.refresh,
                          a.season_from, a.season_to, a.limit_clubs)
        elif a.command == "download":
            from . import download
            download.careers(_countries(a.countries), bf, bt, a.limit, a.refresh, not a.no_secondary)
        elif a.command == "extras":
            from . import download
            download.extras(a.sources.split(","), a.refresh)
        elif a.command in ("normalize", "all"):
            from . import normalize
            normalize.run()
        if a.command in ("features", "all"):
            from . import features
            features.run()
        if a.command in ("targets", "all"):
            from . import targets
            targets.run()
        if a.command in ("validate", "report", "all"):
            from . import report, validate
            v = validate.run()
            if a.command != "validate":
                report.run(v)
                print("reporte -> reports/REPORTE.md")
        if a.command == "status":
            m = manifest()
            for row in m.db.execute("SELECT source, state, consecutive_errors, note FROM source_state"):
                print("fuente", row)
            for row in m.db.execute("SELECT task, status, COUNT(*) FROM tasks GROUP BY task, status ORDER BY task"):
                print("tarea ", row)
            for row in m.db.execute("SELECT source, status, COUNT(*) FROM requests GROUP BY source, status ORDER BY source"):
                print("req   ", row)
        if a.command == "reset-source":
            manifest().set_source_state(a.arg, "ok", 0, "reset manual")
            print(f"{a.arg}: estado reiniciado")
    except KeyboardInterrupt:
        status = "interrupted"
        print("\ninterrumpido: el estado quedo en el manifest; volver a correr el mismo comando reanuda.")
    except Exception:
        status = "error"
        raise
    finally:
        _record_run(a.command, a, status, started)
    return 0


if __name__ == "__main__":
    sys.exit(main())
