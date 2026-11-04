"""Cliente HTTP responsable, compartido por todos los adaptadores.

- Rate limit por dominio (token bucket de capacidad 1 => concurrencia 1) + jitter.
- Backoff exponencial con jitter ante 429/5xx/timeouts; respeta Retry-After.
- Cache en disco: cada respuesta se guarda comprimida en data/raw/<fuente>/<fecha>/.
  Una URL ya descargada no se vuelve a pedir salvo refresh=True.
- Requests condicionales (ETag / Last-Modified) cuando se refresca.
- robots.txt respetado por dominio.
- Circuit breaker: N errores consecutivos detienen la fuente.
- Deteccion de desafios anti-bot (Cloudflare/CAPTCHA): NO se intentan resolver.
  La fuente queda BLOCKED y se informa.
- Manifest SQLite (data/manifests/manifest.sqlite) con URL, estado, hash, fecha,
  intentos y ruta del crudo => reanudacion e idempotencia.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import random
import sqlite3
import threading
import time
import urllib.parse
import urllib.robotparser
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests

from .config import MANIFESTS, RAW, source_cfg
from .logs import RUN_ID, get_logger

RETRY_STATUS = {429, 500, 502, 503, 504}
CHALLENGE_MARKERS = (
    "challenge-platform", "cf-chl-", "cf_chl_", "Just a moment...", "challenges.cloudflare.com",
    "Attention Required! | Cloudflare", "g-recaptcha", "h-captcha", "hcaptcha.com", "px-captcha",
    "Please verify you are a human", "datadome",
)


class SourceBlocked(RuntimeError):
    """La fuente devolvio un desafio anti-bot. No se intenta evadir."""


class SourceDown(RuntimeError):
    """Circuit breaker abierto (demasiados errores consecutivos)."""


class RobotsDisallowed(RuntimeError):
    pass


@dataclass
class FetchResult:
    url: str
    status: int
    text: str
    raw_path: str
    sha256: str
    fetched_at: str
    from_cache: bool
    source: str

    def json(self):
        return json.loads(self.text)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def provenance(self) -> dict:
        return {"source": self.source, "source_url": self.url, "retrieved_at": self.fetched_at,
                "raw_ref": f"{self.raw_path}#{self.sha256[:16]}"}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def looks_like_challenge(status: int, text: str) -> bool:
    if status not in (403, 429, 503) and len(text) > 20000:
        return False
    head = text[:20000]
    return any(m in head for m in CHALLENGE_MARKERS)


class Manifest:
    """Estado persistente de descargas. Seguro para un proceso (lock interno)."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path or MANIFESTS / "manifest.sqlite")
        self.lock = threading.Lock()
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS requests(
              key TEXT PRIMARY KEY, source TEXT, url TEXT, method TEXT, status TEXT,
              http_status INTEGER, fetched_at TEXT, raw_path TEXT, sha256 TEXT,
              etag TEXT, last_modified TEXT, attempts INTEGER DEFAULT 0, error TEXT, run_id TEXT);
            CREATE INDEX IF NOT EXISTS ix_req_source ON requests(source, status);
            CREATE TABLE IF NOT EXISTS source_state(
              source TEXT PRIMARY KEY, state TEXT, consecutive_errors INTEGER, updated_at TEXT, note TEXT);
            CREATE TABLE IF NOT EXISTS tasks(
              task TEXT, item TEXT, status TEXT, updated_at TEXT, note TEXT, run_id TEXT,
              PRIMARY KEY(task, item));
            """
        )
        self.db.commit()

    # --- requests
    def get(self, key: str):
        cur = self.db.execute("SELECT * FROM requests WHERE key=?", (key,))
        row = cur.fetchone()
        if not row:
            return None
        return dict(zip([c[0] for c in cur.description], row))

    def put(self, **kw):
        cols = ",".join(kw)
        q = ",".join("?" for _ in kw)
        upd = ",".join(f"{k}=excluded.{k}" for k in kw if k != "key")
        with self.lock:
            self.db.execute(f"INSERT INTO requests({cols}) VALUES({q}) ON CONFLICT(key) DO UPDATE SET {upd}",
                            tuple(kw.values()))
            self.db.commit()

    # --- estado de fuente
    def source_state(self, source: str) -> dict:
        cur = self.db.execute("SELECT state, consecutive_errors, note FROM source_state WHERE source=?", (source,))
        row = cur.fetchone()
        return {"state": row[0], "errors": row[1], "note": row[2]} if row else {"state": "ok", "errors": 0, "note": ""}

    def set_source_state(self, source: str, state: str, errors: int, note: str = ""):
        with self.lock:
            self.db.execute(
                "INSERT INTO source_state VALUES(?,?,?,?,?) ON CONFLICT(source) DO UPDATE SET "
                "state=excluded.state, consecutive_errors=excluded.consecutive_errors, "
                "updated_at=excluded.updated_at, note=excluded.note",
                (source, state, errors, now_iso(), note))
            self.db.commit()

    # --- tareas (reanudacion a nivel de item: jugador, plantel, consulta)
    def task_status(self, task: str, item: str):
        row = self.db.execute("SELECT status FROM tasks WHERE task=? AND item=?", (task, item)).fetchone()
        return row[0] if row else None

    def set_task(self, task: str, item: str, status: str, note: str = ""):
        with self.lock:
            self.db.execute(
                "INSERT INTO tasks VALUES(?,?,?,?,?,?) ON CONFLICT(task,item) DO UPDATE SET "
                "status=excluded.status, updated_at=excluded.updated_at, note=excluded.note, run_id=excluded.run_id",
                (task, item, status, now_iso(), note[:500], RUN_ID))
            self.db.commit()

    def task_counts(self, task: str) -> dict:
        return dict(self.db.execute("SELECT status, COUNT(*) FROM tasks WHERE task=? GROUP BY status", (task,)).fetchall())


_MANIFEST: Manifest | None = None


def manifest() -> Manifest:
    global _MANIFEST
    if _MANIFEST is None:
        _MANIFEST = Manifest()
    return _MANIFEST


class PoliteClient:
    """Un cliente por fuente. Reutiliza sesion y cookies; headers constantes."""

    _last_hit: dict[str, float] = {}
    _robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def __init__(self, source: str, refresh: bool = False, offline: bool = False, session=None):
        self.source = source
        self.cfg = source_cfg(source)
        self.refresh = refresh
        self.offline = offline  # solo cache (tests / re-normalizacion sin red)
        self.log = get_logger(f"http.{source}")
        self.m = manifest()
        self.session = session or requests.Session()
        ua = self.cfg.get("browser_user_agent") or self.cfg["user_agent"]
        self.session.headers.update({"User-Agent": ua, "Accept-Encoding": "gzip, deflate"})
        self.session.headers.update(self.cfg.get("headers") or {})
        self.stats = {"requests": 0, "cache_hits": 0, "errors": 0}

    # ------------------------------------------------------------------ util
    @staticmethod
    def make_key(method: str, url: str, data=None) -> str:
        body = json.dumps(data, sort_keys=True) if data else ""
        return hashlib.sha1(f"{method} {url} {body}".encode()).hexdigest()

    def _raw_path(self, key: str) -> Path:
        d = RAW / self.source / datetime.now().strftime("%Y-%m-%d")
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{key}.gz"

    def _throttle(self, domain: str):
        rate = float(self.cfg.get("rate", 3.0))
        jitter = float(self.cfg.get("jitter", 1.0))
        wait = rate + random.uniform(0, jitter)
        last = self._last_hit.get(domain, 0.0)
        delta = time.monotonic() - last
        if delta < wait:
            time.sleep(wait - delta)
        self._last_hit[domain] = time.monotonic()

    def _robots_ok(self, url: str) -> bool:
        if not self.cfg.get("respect_robots", True):
            return True
        p = urllib.parse.urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self.session.get(base + "/robots.txt", timeout=30)
                if r.status_code == 200:
                    rp.parse(r.text.splitlines())
                    # se guarda copia del robots leido para auditoria
                    (RAW / self.source).mkdir(parents=True, exist_ok=True)
                    (RAW / self.source / f"robots_{p.netloc}_{datetime.now():%Y%m%d}.txt").write_text(
                        r.text, encoding="utf-8")
                    self._robots[base] = rp
                else:
                    self._robots[base] = None  # sin robots => permitido
            except requests.RequestException:
                self._robots[base] = None
        rp = self._robots[base]
        if rp is None:
            return True
        ua = self.session.headers.get("User-Agent", "*")
        return rp.can_fetch(ua, url)

    def _check_breaker(self):
        st = self.m.source_state(self.source)
        if st["state"] == "blocked":
            raise SourceBlocked(f"{self.source}: fuente marcada BLOCKED ({st['note']}). "
                                f"Revisar y ejecutar `python -m src.pipeline reset-source {self.source}`.")
        if st["state"] == "down":
            raise SourceDown(f"{self.source}: circuit breaker abierto ({st['note']}).")

    def _error(self, note: str):
        self.stats["errors"] += 1
        st = self.m.source_state(self.source)
        n = st["errors"] + 1
        limit = int(self.cfg.get("breaker", 8))
        if n >= limit:
            self.m.set_source_state(self.source, "down", n, note)
            self.log.error("circuit breaker abierto", extra={"data": {"errors": n, "note": note}})
            raise SourceDown(f"{self.source}: {n} errores consecutivos; ultimo: {note}")
        self.m.set_source_state(self.source, "ok", n, note)

    def _success(self):
        st = self.m.source_state(self.source)
        if st["errors"]:
            self.m.set_source_state(self.source, "ok", 0, "")

    # ------------------------------------------------------------------ API
    def get(self, url: str, params: dict | None = None, method: str = "GET", data: dict | None = None,
            headers: dict | None = None, refresh: bool | None = None) -> FetchResult:
        if params:
            url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        key = self.make_key(method, url, data)
        refresh = self.refresh if refresh is None else refresh
        prev = self.m.get(key)

        if prev and prev["status"] in ("ok", "not_found") and not refresh and prev["raw_path"] \
                and Path(prev["raw_path"]).exists():
            self.stats["cache_hits"] += 1
            text = gzip.decompress(Path(prev["raw_path"]).read_bytes()).decode("utf-8", errors="replace")
            return FetchResult(url, prev["http_status"], text, prev["raw_path"], prev["sha256"],
                               prev["fetched_at"], True, self.source)
        if self.offline:
            raise FileNotFoundError(f"offline: {url} no esta en cache")

        self._check_breaker()
        if not self._robots_ok(url):
            self.m.put(key=key, source=self.source, url=url, method=method, status="robots_disallowed",
                       fetched_at=now_iso(), run_id=RUN_ID)
            raise RobotsDisallowed(url)

        domain = urllib.parse.urlparse(url).netloc
        hdrs = dict(headers or {})
        if prev and refresh:
            if prev.get("etag"):
                hdrs["If-None-Match"] = prev["etag"]
            if prev.get("last_modified"):
                hdrs["If-Modified-Since"] = prev["last_modified"]

        max_retries = int(self.cfg.get("max_retries", 5))
        base = float(self.cfg.get("backoff_base", 4.0))
        cap = float(self.cfg.get("backoff_max", 300))
        attempts = (prev or {}).get("attempts") or 0
        last_err = ""
        for attempt in range(max_retries + 1):
            self._throttle(domain)
            attempts += 1
            self.stats["requests"] += 1
            try:
                r = self.session.request(method, url, data=data, headers=hdrs,
                                         timeout=float(self.cfg.get("timeout", 60)))
            except requests.RequestException as e:
                last_err = f"{type(e).__name__}: {e}"
                if attempt < max_retries:
                    time.sleep(min(cap, base * 2 ** attempt) + random.uniform(0, base))
                    continue
                break

            if r.status_code == 304 and prev:
                self._success()
                text = gzip.decompress(Path(prev["raw_path"]).read_bytes()).decode("utf-8", errors="replace")
                self.m.put(key=key, fetched_at=now_iso(), attempts=attempts, run_id=RUN_ID)
                return FetchResult(url, prev["http_status"], text, prev["raw_path"], prev["sha256"],
                                   now_iso(), True, self.source)

            text = r.text
            if looks_like_challenge(r.status_code, text):
                note = f"desafio anti-bot (HTTP {r.status_code}) en {url}"
                self.m.set_source_state(self.source, "blocked", 0, note)
                self.m.put(key=key, source=self.source, url=url, method=method, status="blocked",
                           http_status=r.status_code, fetched_at=now_iso(), attempts=attempts,
                           error=note, run_id=RUN_ID)
                self.log.error("fuente bloqueada por desafio anti-bot; no se intenta evadir",
                               extra={"data": {"url": url, "status": r.status_code}})
                raise SourceBlocked(note)

            if r.status_code in RETRY_STATUS:
                last_err = f"HTTP {r.status_code}"
                ra = r.headers.get("Retry-After")
                if ra and ra.isdigit():
                    wait = min(cap * 4, float(ra))
                else:
                    wait = min(cap, base * 2 ** attempt) + random.uniform(0, base)
                self.log.warning("reintento", extra={"data": {"url": url, "status": r.status_code, "wait": wait}})
                if attempt < max_retries:
                    time.sleep(wait)
                    continue
                break

            status = "ok" if r.ok else ("not_found" if r.status_code in (404, 410) else "http_error")
            raw = text.encode("utf-8")
            sha = hashlib.sha256(raw).hexdigest()
            path = self._raw_path(key)
            path.write_bytes(gzip.compress(raw))
            fetched = now_iso()
            self.m.put(key=key, source=self.source, url=url, method=method, status=status,
                       http_status=r.status_code, fetched_at=fetched, raw_path=str(path), sha256=sha,
                       etag=r.headers.get("ETag"), last_modified=r.headers.get("Last-Modified"),
                       attempts=attempts, error=None if r.ok else f"HTTP {r.status_code}", run_id=RUN_ID)
            if status == "http_error":
                self._error(f"HTTP {r.status_code} {url}")
            else:
                self._success()
            return FetchResult(url, r.status_code, text, str(path), sha, fetched, False, self.source)

        self.m.put(key=key, source=self.source, url=url, method=method, status="error",
                   fetched_at=now_iso(), attempts=attempts, error=last_err, run_id=RUN_ID)
        self._error(last_err)
        raise requests.RequestException(f"{self.source}: agotados reintentos para {url}: {last_err}")

