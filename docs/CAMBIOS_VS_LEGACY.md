# Cambios respecto de los scripts anteriores (`legacy/`)

| Tema | Antes | Ahora | Por qué |
| --- | --- | --- | --- |
| Países | ARG, BRA, URU, COL, ECU | + CHI, PAR | Decisión del usuario |
| Cohorte | Salía de ligas FBref 2014+; madura 1995–2000 | Wikidata + planteles TM de liga y selección desde 1997 + FBref; nacidos 1980–2001 | Los nacidos 1980–1994 no aparecían |
| Umbral de features | `etl_ml_sudamericanos.py` tenía **default 1500** min | **1000** min hasta los 23 (`config/cohort.yaml`) | El usuario indicó 1000; el default del script no coincidía |
| Posición | `Pos` contiene FW en alguna temporada | Primaria de ataque ⇒ incluido; ataque solo secundario ⇒ revisión manual; sin ataque ⇒ excluido (con lista y motivo) | Decisión del usuario |
| Fuente de features | Tablas FBref por temporada, edad aproximada | Partido a partido TM, edad exacta por fecha; dos variantes (`sa_clubs` igual alcance que antes, `all_clubs`) | FBref no cubre ligas SA antes de 2014 |
| penales (`club_pk`, `club_pkatt`, `club_g_minus_pk`) | FBref | FBref si existe; si no, **nulo** | TM no los expone; no se inventan |
| ID global | `Matcher` por nombre con bloque año + primera letra | Anclas TM ID > QID > FBref ID; fuzzy solo con confirmación por DOB o club+temporada | El bloque por primera letra impedía unir apodos y se fusionaba por nombre |
| `player_id` en `etl_fbref_unico.py` | Local a cada liga | `player_uid` global y determinístico | |
| Resolución TM | WRatio ≥ 82; si no había ambigüedad no verificaba nacimiento | Siempre verifica DOB (o año) contra el perfil; empates ⇒ revisión | Mapeos a homónimos |
| Caps TM | `fetch_caps` devolvía 0 si no encontraba el texto | `None` (no leído) distinto de 0; conflicto TM perfil vs TM partidos vs NFT | |
| Juveniles | U17Q/U19Q/U21Q/OLYM sumaban a `tm_min_seleccion` | Tabla `youth_caps` separada | No mezclar con mayor |
| Partidos con 0 minutos | Descartados | Conservados (`appeared=0`) | Convocatorias |
| `min_elite_puente` | Regla UEFA de fallback silenciosa | Misma regla, pero `min_puente_uefa_fallback` separado para auditar | Andorra/San Marino contaban como puente |
| FBref anti-bot | SeleniumBase UC + `uc_gui_handle_captcha` | requests a ~7 s/request; desafío ⇒ BLOCKED; exportes manuales en `data/manual/fbref/` | Política: no resolver CAPTCHA |
| FBref columnas | 25 columnas fijas | Lee las que existan por `data-stat` | FBref perdió Opta en ene-2026 |
| Reintentos | 3 intentos lineales | Backoff exponencial + jitter + `Retry-After` + circuit breaker | |
| Reanudación | CSV de estado; `purge_career` reescribía todo el CSV | Manifest SQLite por URL y por tarea; interim un archivo por item | Idempotencia y rendimiento |
| `scrape_tm_cand.py` | Copia de `scrape_tm_career.py` | Un solo adaptador | |
