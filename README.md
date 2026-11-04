# Cohorte de delanteros sudamericanos 1980–2001

Pipeline reproducible para construir el dataset de **todos los delanteros nacidos entre 1980 y 2001** de Argentina, Brasil, Chile, Uruguay, Paraguay, Colombia y Ecuador, con su carrera completa (clubes y selección mayor) hasta el 2026-11-04, procedencia por fila y reglas de descarga responsable.

Alimenta la red neuronal que predice si un jugador llega a nivel mundial (`target_standard`: caps ≥ 15 o ≥ 3500 min en ligas europeas élite/puente; `target_elite`: caps ≥ 30 o ≥ 8000 min).

## Estructura

```
config/            cohort.yaml (alcance, umbrales, targets), sources.yaml (rate limits, licencias),
                   positions.yaml (mapeo de posiciones), fbref_competitions.yaml, rsssf_pages.yaml
src/common/        http.py (cliente responsable + manifest), store.py, config.py, logs.py, textnorm.py
src/adapters/      wikidata, transfermarkt, fbref, wikipedia, nft, worldfootball, rsssf, espn,
                   api_football, statsbomb, kaggle, soccerway (desactivado), opta (pendiente de licencia)
src/pipeline/      __main__ (CLI), download, normalize, identity, positions, features, targets, validate, report
data/raw/<fuente>/<fecha>/   respuestas crudas comprimidas (.gz), una por URL
data/interim/      datos parseados por item (un JSON por jugador/plantel/consulta)
data/processed/    tablas canónicas en Parquet y CSV
data/manifests/    manifest.sqlite: estado de cada URL, tareas, fuentes, corridas
data/manual/       position_decisions.csv (tus decisiones), exportes manuales de FBref, Kaggle
logs/              logs JSON por fuente y corrida
reports/           REPORTE.md + validation/*.csv
legacy/            scripts anteriores, sin cambios (referencia)
tests/             tests offline con fixtures
docs/              fuentes, política, diccionario de datos, cambios vs legacy, acceso a Opta
```

## Runbook (Windows PowerShell)

### 1. Instalación (una vez)

```powershell
git clone https://github.com/agusdeba/redes-neuronales.git
cd redes-neuronales
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env        # completar CONTACT_EMAIL (lo exige la política de Wikidata/Wikipedia)
python -m pytest -q # tiene que dar todo verde
```

Si PowerShell bloquea `Activate.ps1`: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

### 2. Verificar configuración contra las fuentes (pocas requests)

```powershell
python -m src.pipeline check-config
```

Imprime el nombre que devuelve Transfermarkt para cada código de liga y selección, y si FBref responde o pide un desafío anti-bot. Si un código no corresponde, se corrige en `config/cohort.yaml`.

### 3. Prueba con una muestra pequeña (obligatoria antes de la descarga completa)

```powershell
python -m src.pipeline seed --sources wikidata --countries PAR --born-from 1990 --born-to 1990
python -m src.pipeline seed --sources tm_leagues --countries PAR --season-from 2010 --season-to 2010 --limit-clubs 3
python -m src.pipeline download --countries PAR --born-from 1990 --born-to 1990 --limit 15
python -m src.pipeline all
python -m src.pipeline status
```

Revisar `reports\REPORTE.md`, `data\processed\players.csv`, `data\processed\review_queue.csv` y `reports\validation\audit_sample.csv`.

### 4. Descarga completa (en tandas; se puede cortar con Ctrl+C y retomar)

```powershell
# Semillas (horas). Cada comando retoma donde quedó.
python -m src.pipeline seed --sources wikidata,wikipedia
python -m src.pipeline seed --sources tm_national --season-from 1997 --season-to 2025
python -m src.pipeline seed --sources tm_leagues  --season-from 1997 --season-to 2025
python -m src.pipeline seed --sources fbref
# Carreras completas (días). Se recomienda por país.
foreach ($c in "ARG","BRA","CHI","URU","PAR","COL","ECU") { python -m src.pipeline download --countries $c }
# Fuentes de validación
python -m src.pipeline extras --sources statsbomb,rsssf
# Tablas, features, targets, validación y reporte
python -m src.pipeline all
```

- Volver a correr un comando **no duplica** nada y **no vuelve a descargar** URLs ya guardadas; `--refresh` fuerza la re-descarga.
- Si una fuente devuelve un desafío anti-bot (Cloudflare/CAPTCHA), queda marcada **BLOCKED** y el pipeline sigue con las demás. No se intenta evadir. Para reintentar más tarde: `python -m src.pipeline reset-source fbref`.
- Si una fuente acumula errores seguidos, se abre el circuit breaker (`status` lo muestra); se reinicia igual.

### 5. Revisar la cola de posiciones ambiguas

`data\processed\review_queue.csv` lista los jugadores que juegan de delantero pero **no como primera posición**, y los conflictos entre fuentes. Para decidir, crear `data\manual\position_decisions.csv` (ver `position_decisions.example.csv`) con `include` o `exclude`, y correr `python -m src.pipeline all`.

## Salidas principales (`data/processed/`)

| Tabla | Contenido |
| --- | --- |
| `players` | Delanteros incluidos (1 fila por jugador, sin duplicados) |
| `players_all` | Toda la cohorte con `inclusion_status` y motivo |
| `excluded_players`, `review_queue` | Excluidos y pendientes de tu decisión, con motivo |
| `player_identity` | IDs de cada fuente por jugador, método y puntaje de match |
| `career_stints` | Jugador × temporada × competición × club (TM y FBref) |
| `match_performance` | Partido a partido de clubes (TM) |
| `national_team_caps` / `youth_caps` | Selección mayor / juveniles, separadas |
| `transfers`, `competitions`, `conflicts`, `seed_candidates` | Transferencias, catálogo, conflictos entre fuentes, aporte de cada semilla |
| `features_u23_sa_clubs` / `features_u23_all_clubs` | Tu esquema de 45 columnas, hasta los 23, umbral 1000 min |
| `targets`, `jugadores_target_ml_*` | Targets y dataset final para la red |

Cada fila de hechos lleva `source`, `source_url`, `retrieved_at` y `raw_ref` (archivo crudo + hash).

Ver `docs/DATA_DICTIONARY.md`, `docs/FUENTES.md`, `docs/POLITICA.md`, `docs/CAMBIOS_VS_LEGACY.md` y `docs/OPTA_ACCESO.md`.
