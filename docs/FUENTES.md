# Fuentes: matriz, estado y licencias

Ver `config/sources.yaml` para rate limits y estado habilitado/deshabilitado. Licencias resumidas al 2026-11-04; verificar en cada sitio antes de redistribuir.

| Fuente | Rol | Acceso | Licencia / ToS | Estado en el pipeline |
| --- | --- | --- | --- | --- |
| Transfermarkt | Identidad + carrera completa (principal) | Web + tmapi interna (no documentada) | Propietaria; uso académico de bajo volumen, sin redistribuir crudos | Implementado |
| Wikidata | Semilla de cohorte + IDs cruzados + pasos por equipos | SPARQL oficial | CC0 | Implementado |
| Wikipedia es/pt/en | Descubrimiento por categorías + validación de infobox | API MediaWiki | CC BY-SA 4.0 | Implementado |
| FBref | Estadísticas por temporada (ligas SA 2014+, Big 5, selecciones) | requests con cache; exportes manuales | Sports Reference: uso personal, sin scraping agresivo; sin Opta desde ene-2026 | Implementado, sin evasión de Cloudflare |
| National-Football-Teams | Contraste de caps | HTML | Verificar ToS | Implementado (parser a validar con datos reales) |
| WorldFootball.net | Contraste de carrera | HTML | Verificar ToS | Implementado (parser genérico a validar) |
| RSSSF | Backfill histórico | HTML por página | Copyright de autores, con crédito | Implementado: goleadores; otras páginas, crudo |
| StatsBomb Open Data | Validación de tiros/xG | GitHub | No comercial con atribución | Implementado |
| Kaggle player-scores | Validación/backfill (player_id = TM id) | Kaggle CLI | Verificar en la página del dataset | Implementado (carga local) |
| API-Football | Contraste reciente | API oficial con clave | Licencia del plan | Implementado, requiere `API_FOOTBALL_KEY` |
| ESPN | Contraste reciente | JSON no documentado | Sin licencia explícita de reuso | Implementado, desactivado por defecto |
| Soccerway | Contraste | HTML con anti-bot | ToS restrictivos | Desactivado: si bloquea, se descarta |

## No implementadas (licencia o falta de acceso)

| Fuente | Motivo | Alternativa legal |
| --- | --- | --- |
| Opta / Stats Perform | Licencia comercial, sin credenciales | Pedido de acceso académico (`docs/OPTA_ACCESO.md`); StatsBomb Open Data; API-Football |
| Sofascore | ToS prohíben uso automatizado; solo endpoints internos | API-Football |
| FotMob | Ídem | API-Football |
| BeSoccer | API comercial con clave | Contratar su API si se necesitara |
| FootballDatabase | Sin API pública | WorldFootball / TM |

## Atribución requerida en publicaciones
- Wikidata (CC0, atribución recomendada), Wikipedia (CC BY-SA 4.0), RSSSF (crédito a los autores), StatsBomb (atribución obligatoria), Transfermarkt y FBref (citar como fuente; no redistribuir datos crudos).
