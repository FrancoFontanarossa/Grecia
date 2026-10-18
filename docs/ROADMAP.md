# ROADMAP.md — Entrecasa

> **Versión 1.2** · sábado 17/10/2026, 18:00 · Franco, Guada y Juanpe · build 101
> 1.1 alinea con `CLAUDE.md` v2.1: horarios corridos 30 minutos, Hito 0 en iPhone, biometría por Atajo. 1.2: **Juanpe y Franco intercambian roles** (Juanpe, app y web; Franco, datos, reglas, calidad e infraestructura).
> Va en `docs/ROADMAP.md`. Qué se construye: `CLAUDE.md`. Dónde va cada cosa: `docs/ARQUITECTURA.md`. Cómo se ve: `design/DESIGN.md`.
> Si un hito se atrasa, se corre el resto del plan y se avisa en el grupo; los recortes de la sección 4 no se discuten de madrugada.

---

## 1. Cómo trabajamos

1. **Contratos primero.** A las **18:00** se congelan `app/models.py` y la tabla de la API (CLAUDE.md §11). Desde ahí, cada uno trabaja contra esa forma aunque la pieza del otro no exista todavía, con datos falsos que la respeten.
2. **Esqueleto que funcione de punta a punta antes de que algo esté bueno.** El Hito 0 y la integración de las 19:45 existen para eso. Primero feo y conectado; el pulido visual va al final.
3. **Hitos con cortes decididos de antemano** (sección 4).
4. **Cada uno en su carpeta y su rama**, PRs chicos, `main` siempre corre. Se integra cada ~90 minutos, no solo en los hitos.
5. **Tests en verde para mergear** lo que toque `app/rules/`.
6. **Ninguna prueba de riesgo se pelea más de 45 minutos:** si no sale, se activa el plan B de ARQUITECTURA §12 y se sigue.
7. **Consumo:** revisar Railway y la key de Claude en cada checkpoint.

---

## 2. Quién hace qué

### Guada · la IA y la entrada y salida
**Que el sistema entienda y hable.**
- Conocimiento y taxonomía: `knowledge/parkinson.md`, `app/taxonomy.py`.
- Entrada: `POST /api/entries` (con `/confirm` y `/correct`), `pipeline.transcribe`.
- Todos los prompts: `extract`, `red_backup`, `explain`, `ask` + banco de repreguntas, `report`.
- Salida: `app/notify/` (push + `notifications`) y `app/scheduler.py`.
- `scripts/precorrer_semana.py` (pasa los relatos de la semana por el pipeline real con el reloj).
- Claves VAPID y keys en Railway.
- **Carpetas:** `app/pipeline/`, `app/prompts/`, `app/question_bank/`, `app/notify/`, `app/api/entries.py`, `app/scheduler.py`, `knowledge/`, `scripts/`.
- **No etiqueta el eval** (escribe los prompts).

### Juanpe · la app y la web
**Que se vea y se use como una app.** Armó el diseño: construye igual que `design/screens/`.
- PWA: manifest, service worker, "¿Quién sos?", suscripción push (permiso desde un botón), inicio por rol (Juan, Marta, Laura), contar algo con estados de progreso y "Anoté esto", pregunta con "por qué te pregunto", golpeteo, permisos, pantalla de emergencia.
- Web de la neuróloga: informe con resumen, evidencia clickeable y avisos; vista técnica.
- Panel de admin (UI): reloj, inyectar caída, restaurar.
- Rutas de API que sirven a las pantallas: `hoy`, `questions`, `tests`, `consents`, `push`, `report`, `technical`, `notifications`.
- Segunda etiqueta del eval, por separado y sin ver la primera. Rótulos de lo simulado y pulido visual.
- **Carpetas:** `app/web/`, `app/api/` (salvo `entries`, `biometrics` y `admin`).

### Franco · los datos, las reglas, la calidad y la infraestructura
**Que lo crítico no falle, que se pueda demostrar y que todo esté arriba.**
- Infra: repo, Railway, Tenki Reviewer, CI con Tenki Runner, `railway.toml`, `app/main.py`.
- Base y reloj: `app/db.py`, `app/clock.py` (offset en `clock_state`).
- Datos: prueba del Atajo de iOS (que lea pasos y haga POST) y `POST /api/biometrics/atajo`; exportación de Salud → `data/import_health.py`; `data/seed.py` (personas, consentimientos, esquema de tomas, cambio de pramipexol del 03/10, meta de 4.000 pasos, historial de golpeteo, tres caídas inyectadas). Revisar la franja de 16 a 18 h antes de fijar el escenario.
- Lógica del admin: `clock/advance`, `clock/set`, `inject_drop`, `restore`.
- Todas las reglas con tests: R1–R4, A1–A3, consentimiento, canal reservado, presupuesto y silencio, metas y pausa, **desvío de pasos**, **disparadores proactivos**, **puntaje del golpeteo**, verificador.
- Eval: 30 relatos + primera etiqueta, línea de base léxica, sets de rojos y cebos, canal reservado, fidelidad del informe, `eval/run.py` y `results.md` (la diapositiva sale de esa tabla).
- **Carpetas:** raíz, `.github/`, `app/main.py`, `app/db.py`, `app/clock.py`, `app/rules/`, `tests/rules/`, `app/api/biometrics.py`, `app/api/admin.py`, `data/`, `eval/`.
- `app/models.py` lo escribe con Guada.

---

## 3. Cronograma (corrido 30 minutos)

| Hora | Guada | Juanpe | Franco |
|---|---|---|---|
| **17:30–18:00** · Setup | Keys en Railway; claves VAPID; `models.py` con Franco | Leer `design/` y la sección 9 de CLAUDE.md; plantilla base Jinja con `tokens.css` y la tipografía | Repo con los 4 documentos y `design/`, Railway con volumen, Tenki, CI; exportación de Salud en marcha; `models.py` con Guada |
| **18:00** | **Contratos congelados**: `models.py` + tabla de la API | | |
| **18:00–19:30** | `POST /api/entries` con texto y transcripción; envío de push | Esqueleto de la PWA: manifest, `sw.js`, "¿Quién sos?", suscripción push con botón; inicio de Juan feo pero conectado; deploy | Prueba del Atajo + `POST /api/biometrics/atajo`; `db.py`, `clock.py`, `import_health.py`, `seed.py` con los pasos |
| **19:30 · Hito 0** | ✅ En un **iPhone**, con la app agregada a la pantalla de inicio desde Railway: un texto escrito se guarda, llega una push "Recibido" (sin IA) con la app cerrada y el Atajo manda pasos que aparecen en la base. **Probar también el micrófono en modo app** | | |
| **19:30–20:30** | Conocimiento y taxonomía; `extract`; repregunta; `red_backup`; scheduler | Contar algo con grabación, estados de progreso y "Anoté esto"; inicio de Marta; pregunta proactiva; golpeteo | Reglas con tests (rojos y canal reservado primero); desvío de pasos; disparadores; puntaje del golpeteo |
| **19:45 · Integración** | Un texto escrito en la app aparece como eventos en la base de Railway | | |
| **20:30 · Checkpoint** | ✅ Marta graba en la app → "Anoté esto" → ámbar en el informe, y Juan no recibe nada. Caída inyectada → push a Juan → respuesta → episodio. Un rojo dispara la push y la pantalla fija. Medir latencia y consumo | | |
| **20:30–21:00** | `explain` + `ask` con la pregunta disparada por push | Resumen de Laura; panel de admin | Lógica del admin; 30 relatos + primera etiqueta (los borradores se escriben en los ratos de espera desde temprano) |
| **21:00–21:30** | Traslado. Railway sigue vivo. Llamada abierta el resto de la noche | | |
| **21:30–23:30** | `report` + integración del verificador; regeneración en segundo plano | Informe de la neuróloga con resumen, evidencia clickeable y vista técnica; permisos; pantalla de emergencia | Sets de rojos y cebos; línea de base; verificador con tests; `eval/run.py` |
| **23:30 · Congelamos features** | Otro equipo prueba la app desde sus celulares con sus propias frases, en el paciente de prueba; arreglamos | | |
| **23:30–01:00** | Robustez, errores, latencia; `precorrer_semana.py` | Segunda etiqueta del eval; rótulos; pulido visual contra `design/` | Corrida final del eval; `results.md`; declaración de lo simulado en el README; tag `demo-v1` |
| **01:00** | Video de respaldo grabado contra Railway. A dormir | | |

### Domingo
| Hora | Qué |
|---|---|
| 7:30 | Smoke test en Railway: la app abre en los tres iPhone, llega una push, el reloj está en el lunes, créditos de Railway y de Claude |
| 7:45 | En este orden: `data/seed.py` → `scripts/simular_pulsera.py` → `scripts/precorrer_semana.py` → reloj (`POST /admin/clock/set`) → `POST /admin/snapshot` (justo antes de la caída en vivo) |
| 8:00–8:45 | Pitch entre los tres; ensayo cronometrado tres veces, con las preguntas de `docs/PRODUCTO.md` en voz alta y `POST /admin/restore` entre ensayos |
| **8:45** | **Nadie pushea a `main`** |
| ¿9:00–11:00? | Presentación (**confirmar el horario con la organización**) |

---

## 4. Hitos y recortes

**Hito 0 (19:30)** — app agregada a la pantalla de inicio de un iPhone desde Railway, texto guardado, push "Recibido" (sin IA) recibida con la app cerrada, pasos del Atajo en la base, micrófono probado. Es la parte nueva y más riesgosa. Si la push no anda en 45 minutos, se pasa al plan B (todo visible desde `notifications` al abrir la app) y se sigue.

**Integración (19:45)** — texto en la app → eventos en la base de Railway.

**Checkpoint (20:30)** — si falla, se recorta en este orden:
1. La vista técnica queda en un solo gráfico.
2. El resumen de Laura queda solo con el logro.
3. La meta de pasos sin aviso a la familia.

Ya están fuera de P0 desde el cambio a las bases: **encargo**, **mensaje de logro redactado por IA**, **confirmar tomas**, **A4**, **botonera** y **WhatsApp**.

**Nunca se recortan:** contar algo con "Anoté esto", push con plan B, rojos, canal reservado, proactividad (desvío → explicar → preguntar), golpeteo, informe con verificador y eval.

**Congelamiento (23:30)** — después de esta hora solo se arreglan errores y se pule lo visual; nada nuevo.

---

## 5. Antes de empezar (checklist del setup)

- [ ] Repo con `CLAUDE.md`, `docs/PRODUCTO.md`, `docs/ARQUITECTURA.md`, `docs/ROADMAP.md` y `design/`
- [ ] Guada y Juanpe como colaboradores en GitHub
- [ ] Railway conectado al repo, volumen en `/data`, dominio generado, `/health` respondiendo
- [ ] Variables en Railway: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `VAPID_*`, `ATAJO_TOKEN`, `ADMIN_TOKEN`, `DEMO_MODE=1`
- [ ] Tenki Code Reviewer instalado en el repo
- [ ] CI corriendo (aunque `tests/rules` esté vacío)
- [ ] iOS 16.4 o más en los tres iPhone
- [ ] Exportación de Salud en camino y Atajo probado
- [ ] Lienzo de diseño compartido con los tres
- [ ] Alguien de otro equipo comprometido a probar a las 23:30
- [ ] Horario del domingo confirmado con la organización
