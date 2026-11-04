# Política de descarga responsable

1. **No se evaden controles de acceso.** No se resuelven CAPTCHAs, no se usa `undetected-chromedriver`/SeleniumBase UC ni `uc_gui_handle_captcha`, no se rotan IPs ni User-Agents, no se usan proxies para burlar bloqueos. Los scripts anteriores que lo hacían quedan en `legacy/` solo como referencia y no se ejecutan desde el pipeline.
2. **Desafío anti-bot = fuente BLOCKED.** `src/common/http.py` detecta páginas de Cloudflare/CAPTCHA/DataDome, marca la fuente como bloqueada en el manifest, lo registra y deja de pedirle. El resto del pipeline sigue.
3. **robots.txt** se respeta por dominio; se guarda una copia del archivo leído en `data/raw/<fuente>/` para auditoría.
4. **Preferencia por vías oficiales:** Wikidata SPARQL (CC0), API MediaWiki, StatsBomb Open Data, API-Football con clave, datasets con licencia. Scraping HTML solo donde no hay alternativa, a baja tasa.
5. **Ritmo:** concurrencia 1 por dominio, intervalo mínimo configurable por fuente (`config/sources.yaml`) más jitter aleatorio. FBref a 1 request cada ~7 s (límite publicado ~10/min); Transfermarkt cada ~4–6 s.
6. **Errores:** backoff exponencial con jitter ante 429/5xx/timeouts, respeto de `Retry-After`, circuit breaker tras N errores consecutivos.
7. **Cache:** ninguna URL se pide dos veces salvo `--refresh`; en refresh se usan `ETag`/`Last-Modified`.
8. **Datos:** solo información deportiva pública (identidad, posición, partidos, minutos, goles, caps, transferencias). No se guardan datos personales innecesarios.
9. **Proxies:** no se usan. Si en el futuro hiciera falta, solo un proveedor autorizado, configurable y opcional; nunca proxies gratuitos.
10. **Auditoría:** cada request queda en `data/manifests/manifest.sqlite` (URL, fecha, estado, intentos, hash del crudo) y en `logs/`.
11. **Fuentes licenciadas** (Opta/Stats Perform) no se scrapean: ver `docs/OPTA_ACCESO.md`.
