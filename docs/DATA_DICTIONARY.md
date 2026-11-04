# Diccionario de datos

Todas las tablas están en `data/processed/<tabla>.parquet` y `.csv`. Las tablas de hechos llevan siempre `source`, `source_url`, `retrieved_at` (UTC) y, cuando aplica, `raw_ref` (ruta del crudo + prefijo de su SHA-256).

## players / players_all / excluded_players

| Campo | Tipo | Descripción |
| --- | --- | --- |
| player_uid | str(16) | sha1 del ancla (`tm:<id>` > `wd:<qid>` > `fb:<id>`), determinístico |
| canonical_name | str | Nombre preferido (perfil TM > Wikidata > plantel TM > FBref) |
| full_name | str | Nombre completo (TM "Name in home country" o Wikidata P1477) |
| dob | date | Fecha de nacimiento exacta, si existe |
| dob_confidence | str | `exact` o `year_only` |
| birth_year | int | Año de nacimiento |
| nationality | str | País de la cohorte (ARG, BRA, CHI, URU, PAR, COL, ECU) |
| nationality_secondary | str | Otros países de la cohorte, separados por `;` |
| citizenship_all | str | Todas las ciudadanías según TM |
| position_group | str | attack, attack_secondary, attack_conflict, ambiguous, midfield, defense, goalkeeper, unknown |
| position_raw | str | Posición original por fuente (`fuente=valor; ...`) |
| position_evidence | str | Fuentes que aportaron posición |
| inclusion_status | str | included, review, excluded, unknown |
| inclusion_reason | str | Regla aplicada |
| height | int | cm (TM) |
| foot | str | right, left, both (TM) |
| debut_date | date | Primer partido oficial de club con minutos (TM) |
| retirement_date | date | TM "Retired since" |
| is_active | bool | Sin fecha de retiro en TM |
| tm_id, qid, fbref_id, nft_id, worldfootball_id | str | IDs externos |
| caps_tm_profile, nt_goals_tm_profile | int | Caps/goles de selección mayor del perfil TM (nulo = no leído) |
| seeds | str | Semillas que encontraron al jugador |
| source_primary | str | Fuente ancla |
| last_updated | datetime | Fecha de construcción de la fila |

## player_identity
player_uid, source, source_id, source_url, match_score (0–100), match_method (`exact_id`, `fuzzy+dob`, `fuzzy+club_season`, `new_cluster`), verified, notes.

## career_stints
player_uid, source, club_id, club_name, competition_id, competition_name, category (elite, puente, puente_uefa_fallback, continental, otra), country (id TM), season, start_date, end_date, appearances (con minutos), squad_calls (incluye 0 minutos), starts, minutes, goals, assists, yellow_cards, red_cards, competition_tier. Filas FBref agregan pk, pkatt, xg, xag, pos, method (`requests` o `manual_export`).

## match_performance
player_uid, source, date, season, competition_id, competition_name, category, club_id, club_name, opponent, home_away, minutes, appeared, started, goals, assists, yellow, red, cards, shots, xg, xa, position_played. (shots/xg/xa nulos con TM.)

## national_team_caps / youth_caps
player_uid, source, team, level (`senior` / `youth_or_other`), competition, tournament (código TM: FS amistoso, WMQ* eliminatorias, COPA, FIWC Mundial, CF1 Confederaciones), date, season, opponent, minutes, appeared, started, goals, assists, captain.

## competitions
competition_id, name, country, confederation, tier, type, category, source, source_url.

## transfers
player_uid, tm_id, date, season, from_club, to_club, fee, is_loan.

## conflicts
player_uid, field (dob, caps, …), source_a, value_a, source_b, value_b, resolution, reviewed.

## review_queue
player_uid, type (`position` o `identity`), name, birth_year, nationality, candidate_uid, score, reason, source, source_url.

## seed_candidates
player_uid, seed (wikidata, wikipedia, tm_league, tm_national_team, fbref_*, tm_profile), source, name, source_url.

## features_u23_sa_clubs / features_u23_all_clubs
Mismo esquema de 45 columnas que `jugadores_sudamericanos_etl.csv`. `player_id_global` = player_uid. Todas las sumas son hasta los 23 años, calculados con la fecha de cada partido. `minutes_u23_total` = club + selección mayor; filtro ≥ 1000.

## targets / jugadores_target_ml_*
min_elite, min_puente (incluye fallback UEFA), min_puente_uefa_fallback, min_elite_puente, min_continental, caps (perfil TM o, si falta, partidos TM), caps_source, caps_tm_matches, tm_resuelto, target_standard, target_elite.

## source_runs (en manifest.sqlite)
run_id, command, started_at, finished_at, status, args, config_hash, code_version, requests, errors.
