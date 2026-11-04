# Opta: estado y vías legales de acceso

**Estado:** pendiente de licencia. El usuario no tiene credenciales (2026-11-04).

Opta pertenece a Stats Perform y es una fuente comercial. No hay forma legítima de obtener sus datos sin un acuerdo: no se scrapean TheAnalyst, widgets embebidos en medios ni endpoints propietarios, porque eso violaría sus términos y los de los sitios que la licencian. Desde enero de 2026 tampoco llega vía FBref (Sports Reference dejó de mostrar los datos avanzados de Opta).

## Cómo pedir acceso

1. **Programa académico / investigación.** Stats Perform atiende pedidos de investigación caso por caso. Conviene escribir desde un correo institucional, con aval de un docente o director, explicando el uso no comercial.
2. **Contacto comercial.** Formulario de contacto de Stats Perform (statsperform.com → Contact). Se puede pedir un subconjunto acotado: ligas de Sudamérica 2000–2025 y estadísticas por jugador y temporada.
3. **A través de la universidad.** Algunas universidades ya tienen convenios con proveedores de datos deportivos (Stats Perform, Wyscout/Hudl, StatsBomb). Vale preguntar en la biblioteca o en el departamento.

Cuando llegue un contrato, se completa `src/adapters/opta.py` contra la API que indique Stats Perform (Opta SDAPI), con las claves en `.env` (`OPTA_API_KEY`, `OPTA_OUTLET_KEY`).

## Borrador de correo (para enviar vos)

> **Asunto:** Pedido de acceso académico a datos Opta: tesis sobre desarrollo de delanteros sudamericanos
>
> Estimado equipo de Stats Perform:
>
> Soy [nombre], estudiante de [carrera] en [universidad]. Estoy desarrollando, bajo la dirección de [docente], una red neuronal que estima la probabilidad de que un delantero sudamericano (Argentina, Brasil, Chile, Uruguay, Paraguay, Colombia y Ecuador, nacidos entre 1980 y 2001) llegue a jugar en ligas europeas de élite o a ser internacional con su selección.
>
> El proyecto es académico y no comercial. Usamos hoy fuentes abiertas (Wikidata, StatsBomb Open Data) y nos interesaría validar y enriquecer el modelo con estadísticas por jugador y temporada de Opta (minutos, goles, asistencias, tiros, xG, xA, acciones por posición) para las ligas de primera división de esos países y las competiciones CONMEBOL, de 1997 a 2025.
>
> ¿Existe un programa de acceso para investigación, o una licencia académica acotada? Podemos firmar los términos de uso que correspondan, citar la fuente y no redistribuir los datos.
>
> Muchas gracias,
> [nombre] · [correo institucional] · [universidad]

## Alternativas legales mientras tanto

| Necesidad | Alternativa | Limitación |
| --- | --- | --- |
| xG / tiros | StatsBomb Open Data (`extras --sources statsbomb`) | Solo torneos liberados (Mundiales, Copa América 2024, etc.) |
| Estadísticas recientes por temporada | API-Football con clave (`API_FOOTBALL_KEY`) | Cobertura desde ~2010; plan gratuito de 100 requests/día |
| Minutos, goles, asistencias de toda la carrera | Transfermarkt (fuente principal del pipeline) | Sin métricas avanzadas |
