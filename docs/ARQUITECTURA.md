# ARQUITECTURA.md — Entrecasa

> **Versión 1.2** · sábado 17/10/2026, 18:00 · Franco, Guada y Juanpe · build 101
> 1.2: Juanpe y Franco intercambian roles (columna "Dueño").
> 1.1 alinea con `CLAUDE.md` v2.1 (las bases: biometría + relatos + proactividad + golpeteo; iPhone; Atajo de iOS; diseño en `design/`).
> Va en `docs/ARQUITECTURA.md`. Complementa a `CLAUDE.md`: **CLAUDE.md manda en alcance, reglas y contratos**; este archivo manda en **dónde vive cada cosa, cómo se conecta y cómo se despliega**. Lo visual manda `design/DESIGN.md`. Si se contradicen, se avisa en el grupo y se corrige uno de los dos.
> El plan de trabajo está en `docs/ROADMAP.md`.

---

## 1. En una línea

Un solo programa en Python, desplegado en **Railway**, que sirve **la app de la casa** (una PWA para Juan, Marta y Laura), **la web de la neuróloga** y **la API**, recibe los **pasos del iPhone** por un Atajo de iOS, corre el **reloj de demo** y el **scheduler**, llama a **Claude** y a **Whisper**, y guarda todo en **un archivo SQLite** dentro de un volumen persistente.

```
  iPhone de Juan / Marta / Laura         Atajo de iOS (Salud → pasos)      Compu de la neuróloga
  (PWA instalada)                                  │                        (web)
        │  ▲ push                                  │ POST                     │
        │  │                                       │                          │
┌───────▼──┴──────────────── Railway · 1 servicio · 1 worker ───────────────▼──┐
│  app/api (FastAPI) ──► app/pipeline (IA) ──► Claude · Whisper                │
│      │                      ▲                                                │
│      ▼                      │                                                │
│  app/rules (código puro, tests: rojos, carriles, desvío, disparadores…)      │
│      ▲                      │                                                │
│  app/clock + app/scheduler ─┘          app/notify ──► Web Push (Apple)       │
│                 SQLite + audios en el volumen (/data)                        │
└──────────────────────────────────────────────────────────────────────────────┘
GitHub ─PR─► Tenki Code Reviewer + tests en Tenki Runner ─merge─► main ─► Railway redespliega
```

**Por qué un solo proceso:** la base es un único archivo SQLite. Si la API, el scheduler y la web corrieran en lugares distintos, cada uno tendría su propia base. Además, a las 21 nos mudamos de la sede: nada importante puede correr en una laptop.

---

## 2. Componentes

| Componente | Qué hace | Dónde vive | Dueño |
|---|---|---|---|
| **App de la casa (PWA)** | Inicio según el rol, contar algo (audio o texto) con "Anoté esto", pregunta proactiva, golpeteo, logros, permisos, pantalla de emergencia. Recibe push. Construida igual que `design/screens/` | `app/web/casa/`, `app/web/static/` | Juanpe |
| **Web de la neuróloga** | Informe (resumen redactado, 3 temas, evidencia, avisos en la columna lateral) y vista técnica | `app/web/neuro/` | Juanpe |
| **Panel de admin** | Ver, adelantar y fijar la hora; inyectar una caída de pasos (rotulada); restaurar la base | `app/web/admin/` | Juanpe (UI) · Franco (lógica) |
| **API** | Las puertas por donde la app y el Atajo mandan y piden datos (sección 5) | `app/api/` | Guada (`entries`) · Franco (`biometrics`, `admin`) · Juanpe (resto) |
| **Pipeline (IA)** | transcribe, extract, red_backup, explain, ask, report | `app/pipeline/`, `app/prompts/`, `app/question_bank/`, `knowledge/`, `app/taxonomy.py` | Guada |
| **Notify** | Entrega por push lo que las reglas ya aprobaron y lo guarda en `notifications` | `app/notify/` | Guada |
| **Scheduler** | En cada tick: disparadores proactivos (desvío post-toma, noches, silencio, golpeteo, repetición) y progreso de meta | `app/scheduler.py` | Guada |
| **Reglas** | Rojos, carriles, cambio de medicación, desvío, disparadores, consentimiento, canal reservado, presupuesto y silencio, metas, puntaje del golpeteo, verificador | `app/rules/` + `tests/rules/` | Franco |
| **Biometría** | Endpoint del Atajo (API) e importación de la exportación de Salud (datos) | `app/api/biometrics.py` · `data/import_health.py` | Franco |
| **Reloj** | `clock.now()` único, con el offset guardado en la base | `app/clock.py` | Franco |
| **Base** | Esquema de CLAUDE.md §12 | `app/db.py` | Franco |
| **Datos y eval** | Pasos reales, seed, sets y corrida del eval | `data/`, `eval/` | Franco |
| **Infra** | Railway, CI, Tenki, `railway.toml` | raíz, `.github/` | Franco |

`app/models.py` (contratos) lo escriben Guada y Franco juntos; Juanpe revisa la tabla de la API.

---

## 3. Recorridos

### 3.1 Alguien cuenta algo
1. Marta abre la app (o toca una notificación), elige "¿cuándo pasó?" y graba o escribe.
2. La app manda el audio o el texto a `POST /api/entries` y muestra los estados de progreso de `design/DESIGN.md` §5 ("Pasando a texto…", "Entendiendo lo que contaste…").
3. Dentro del mismo pedido: `pipeline.transcribe` (si es audio) → **primero** `rules.red.check` sobre el texto (código, sin IA), con `pipeline.red_backup` (Haiku) que puede **subir** a rojo, nunca bajar → si no es rojo, `pipeline.extract` → eventos validados con Pydantic; el código calcula `is_new` y `reserved`.
4. `rules.lanes.evaluate` → avisos. `rules.consent.recipients` → a quién. `rules.budget` decide si sale ahora o va al resumen.
5. `notify` entrega y guarda en `notifications`.
6. La API devuelve `{transcript, understood, red, alerts}` → la app muestra "Anoté esto" / "Lo que entendimos". "Corregir" llama a `/correct` y reemplaza los eventos de esa entrada; "Sí, está bien" llama a `/confirm`.

**Por qué un solo paso** (y no transcribir → confirmar → procesar): menos toques para Juan, el rojo sale sin esperar una confirmación y el jurado ve el resultado de una. La corrección sigue disponible.

### 3.2 El sistema pregunta
1. El scheduler, en cada tick, corre `rules.triggers.evaluate(patient_id, clock.now())`.
2. Para el desvío: dos horas después de cada toma del esquema, `rules.episodes.deviation` compara los pasos con la línea de base (CLAUDE.md §7.3).
3. Si hay disparador: `pipeline.explain` intenta explicarlo con los relatos previos. Si lo explica, se guarda y no se molesta.
4. Si no: `rules.budget.allow` → `pipeline.ask` redacta la pregunta y 3 respuestas rápidas → se crea una `question` con `why` (cifras del código) → `notify` manda la push.
5. Juan toca la notificación → `/casa/pregunta/{id}` con "Por qué te pregunto" → responde con un toque o con la voz → sigue el recorrido 3.1 → la app le ofrece el golpeteo.

### 3.3 Rojo
`rules.red.check` dispara → `notify` manda push inmediata (sin presupuesto ni silencio) a quien corresponda y la app muestra la **pantalla fija de emergencia** con el guion para la emergencia móvil. Si falta un criterio, la app pregunta solo ese. La meta queda en pausa.

### 3.4 Pasos del iPhone
El Atajo de iOS lee pasos de Salud y hace `POST /api/biometrics/atajo` con el token del paciente (con un botón o por automatización 2 h después de cada toma). La historia de 4 semanas entra con `data/import_health.py`. Todo queda en `biometrics` con su `source`.

### 3.5 Informe
La neuróloga abre `/neuro/informe/{patient}` → el código calcula las cifras → `pipeline.report` (Sonnet) escribe el resumen y elige y redacta tres temas → `rules.verifier.verify` borra lo que no coincide → se muestra con evidencia clickeable y la cuenta de líneas borradas. Se regenera en segundo plano como máximo una vez cada 30 s cuando entra un evento.

---

## 4. Decisiones técnicas fijas

1. **Un servicio, un worker.** `uvicorn ... --workers 1`. Railway no deja réplicas con volumen, y SQLite no aguanta escritores en paralelo.
2. **Todo lo persistente va en el volumen.** El disco del contenedor se borra en cada redeploy. `DATA_DIR = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", "./data")`; la base en `DATA_DIR/entrecasa.db`, los audios en `DATA_DIR/audios/`.
3. **El offset del reloj se guarda en la base** (`clock_state`), no en memoria. Si no, cada redeploy vuelve la semana de Juan al lunes.
4. **El scheduler es idempotente.** Antes de crear una pregunta o un aviso programado, revisa si ya existe para ese día y ese disparador. Un reinicio no duplica nada.
5. **El scheduler corre dentro del proceso**, como tarea de asyncio arrancada en el `lifespan` de FastAPI. Tick cada 30 segundos de reloj real, y también al llamar a `/admin/clock/advance`, `set` o `inject_drop` (procesa todo lo que quedó entre la hora vieja y la nueva, en orden).
6. **HTTPS es obligatorio**: la PWA lo exige para el service worker, las push y el micrófono. Railway lo da con el dominio generado.
7. **Sin login.** Al abrir la app por primera vez se elige quién sos (Juan, Marta o Laura), se guarda en el celular y se registra la suscripción push de esa persona (el permiso se pide desde un botón). Rotulado en pantalla como "modo demo".
8. **Las reglas deciden, notify entrega.** `notify` nunca decide a quién avisar ni si corresponde: eso es `rules/` con tests.
9. **Toda notificación queda también en la base** (`notifications`). El inicio la muestra aunque la push no haya llegado: la push es un aviso, no la única vía.
10. **Las respuestas de la IA se procesan dentro del pedido** (sin colas). La app muestra estados de carga. Si una llamada a Claude falla dos veces, la API devuelve un error claro y la entrada queda guardada con el texto crudo.
11. **Front sin build:** Jinja + HTMX + JS plano, estilos con `design/tokens.css`. Nada de Node en Railway.

---

## 5. API (se congela junto con `models.py` a las 18:00; el detalle de entradas y salidas está en CLAUDE.md §11)

**App de la casa (JSON)**
| Método y ruta | Qué hace |
|---|---|
| `GET /api/people?patient_id=` | Personas del paciente para el selector de rol |
| `POST /api/push/subscribe` | `{person_id, subscription}` → guarda la suscripción push |
| `GET /api/hoy/{person_id}` | Según el rol: pasos de hoy y meta, próxima toma, pregunta pendiente, lo último anotado, notificaciones sin leer; para la familia, además avisos, semana de pasos y logros |
| `POST /api/entries` | `multipart`: `person_id`, `text` o `audio`, `occurred_hint?`, `question_id?`, `quick_reply?`, `reserved_requested?` → procesa todo y devuelve `{entry_id, transcript, understood, red?, alerts}` |
| `POST /api/entries/{id}/confirm` | Marca "Sí, está bien" |
| `POST /api/entries/{id}/correct` | `{text}` → vuelve a extraer y reemplaza los eventos |
| `GET /api/questions/{id}` | La pregunta, el "por qué" con sus cifras y las respuestas rápidas |
| `POST /api/tests` | Toques del golpeteo `{person_id, type, taps: [{t_ms, side}]}` → puntaje y últimas sesiones |
| `GET/POST /api/consents/{patient_id}` | Interruptores por destinatario y tipo |
| `POST /api/notifications/{id}/read` | Marca una notificación como leída |

**Biometría**
| Método y ruta | Qué hace |
|---|---|
| `POST /api/biometrics/atajo` | Encabezado `X-Atajo-Token`; `AtajoPayload`: `{window_start, window_end, samples: [{kind, value, start, end}]}` → guarda las muestras en `biometrics` con `source=atajo` y la ventana en `biometric_syncs`. En `DEMO_MODE` corre las fechas según el offset del reloj |

**Neuróloga (JSON para las vistas)**
- `GET /api/patients/{id}/report` · `GET /api/patients/{id}/technical`

**Páginas (HTML)**
- App de la casa: `/` (¿Quién sos?), `/casa`, `/casa/contar`, `/casa/anote/{entry_id}`, `/casa/pregunta/{id}`, `/casa/golpeteo`, `/casa/permisos`, `/casa/emergencia/{alert_id}`, `/prueba`
- Neuróloga: `/neuro/informe/{patient_id}`, `/neuro/tecnica/{patient_id}`
- Admin: `/admin/clock` (panel HTML), `GET /admin/clock/state` (JSON: `{now, offset_seconds}`), `POST /admin/clock/advance`, `POST /admin/clock/set`, `POST /admin/inject_drop`, `POST /admin/snapshot`, `POST /admin/restore` (con `ADMIN_TOKEN`)
- Infra: `GET /health`, `GET /manifest.webmanifest`, `GET /sw.js` (servido desde la raíz para que controle toda la app)

---

## 6. Notificaciones

**Cómo funciona Web Push:** el navegador del celular genera una *suscripción* (una dirección única) y la app la manda a `/api/push/subscribe`. Para avisar, el servidor firma el mensaje con las **claves VAPID** y lo manda con `pywebpush` al servicio de push de Apple, que lo entrega. En el celular, el **service worker** (`sw.js`) lo recibe y muestra la notificación aunque la app esté cerrada; al tocarla, abre la URL del aviso.

- Las claves VAPID se generan **una vez** (`npx web-push generate-vapid-keys` o `py-vapid`) y van como variables. Si se regeneran, todas las suscripciones dejan de servir.
- **iPhone (los tres tenemos iPhone):** iOS 16.4 o más; la app tiene que estar agregada a la pantalla de inicio y abrirse desde el ícono; el permiso se pide desde un botón que la persona toca; no hay botones de acción en la notificación. **Android:** funciona desde Chrome, instalada o no (para jurados con Android).
- En local, `localhost` cuenta como seguro: se puede probar push en Chrome de escritorio. En el celular, solo contra Railway.
- Nunca va contenido reservado en el cuerpo de una notificación (se ve en la pantalla bloqueada).

**Política de canales** (las reglas ya decidieron a quién; esto es solo por dónde):

| Tipo | P0 | Después |
|---|---|---|
| Rojo | Push inmediata + pantalla fija en la app | + WhatsApp a Marta (P2) |
| Ámbar al equipo | Informe de la neuróloga (columna de avisos) | — |
| Ámbar a la familia | Una push por día con el resumen | — |
| Pregunta proactiva y repregunta | Push que abre la pregunta | — |
| Logro | Push a Marta y Laura (si Juan lo habilitó) | WhatsApp a Laura (P2) |
| Recordatorio de toma | — | Push (P1, junto con confirmar la toma) |

Toda notificación se guarda en `notifications`, haya llegado la push o no.

**WhatsApp (P2):** solo sería viable con el sandbox de Twilio (cada número se suma mandando un código); la API oficial tarda días por la verificación de Meta. No se arma este fin de semana salvo que todo lo demás esté terminado.

---

## 7. Modelo de datos

El esquema completo está en CLAUDE.md §12. Respecto de la versión con Telegram: `people` pierde `telegram_chat_id` y suma `phone?`; se suman `push_subscriptions`, `notifications`, `clock_state`, `biometrics` (reemplaza a `steps`), `biometric_syncs` (cada envío del Atajo o importación con su ventana `window_start`–`window_end`, `received_at` y `n_samples`: distingue "sin datos" de "0 pasos"), `questions` con `rule_id`, `why`, `options` y `url`, y `tests` para el golpeteo.

---

## 8. Estructura del repo

```
CLAUDE.md
docs/
  PRODUCTO.md  ARQUITECTURA.md  ROADMAP.md
design/               # DESIGN.md, tokens.css, screens/*.html  ← referencia visual
app/
  main.py             # FastAPI + lifespan (arranca el scheduler)
  clock.py  config.py  models.py  db.py  scheduler.py  taxonomy.py
  api/                # entries.py, hoy.py, questions.py, biometrics.py, tests.py, consents.py, push.py, report.py, admin.py
  notify/             # policy.py, push.py, inbox.py
  pipeline/           # transcribe, extract, red_backup, explain, ask, report
  rules/              # red, lanes, med_change, episodes, triggers, consent, budget, goals, games, verifier
  prompts/            # prompts versionados .md
  question_bank/      # repreguntas fijas
  web/
    casa/             # templates de la PWA
    neuro/            # templates de la neuróloga
    admin/            # panel del reloj
    static/           # manifest.webmanifest, sw.js, icons/, js/ (grabar, push, golpeteo), css/tokens.css
knowledge/            # parkinson.md
data/                 # seed.py, import_health.py (las exportaciones de Salud no se suben)
scripts/              # precorrer_semana.py
eval/                 # sets/, baseline_lexico.py, run.py, results.md
tests/                # tests/rules/ tiene que pasar siempre
railway.toml  requirements.txt  .python-version  .env.example  .gitignore
.github/workflows/tests.yml
```

**Front:** páginas de FastAPI con Jinja + HTMX (con `hx-boost` para navegar sin recargar, así la PWA se siente app) y JS plano (Alpine.js por CDN si hace falta estado local) para grabar (`MediaRecorder`, en iPhone graba `audio/mp4`), push y golpeteo. Estilos con `design/tokens.css` copiado a `static/css/`. Gráficos con Chart.js por CDN. Las pantallas se construyen igual que `design/screens/`. Sin framework de front ni build aparte.

---

## 9. Deploy en Railway

**Qué es:** un PaaS. Construye el contenedor desde el repo, lo corre, le da HTTPS y lo redespliega con cada merge a `main`. Equivalencias con AWS: *service* ≈ una EC2 como contenedor; *volume* ≈ un EBS; *Generate Domain* ≈ ALB + ACM; *variables* ≈ variables de entorno.

**Configuración en el repo:**
```toml
# railway.toml
[deploy]
startCommand = "uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1"
healthcheckPath = "/health"
```
`.python-version` con `3.12`. `$PORT` lo define Railway.

**Configuración en Railway (una vez):**
1. Proyecto desde el repo de GitHub, rama `main`.
2. Volumen montado en `/data`.
3. Variables: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT=mailto:…`, `ATAJO_TOKEN`, `ADMIN_TOKEN`, `DEMO_MODE=1`.
4. Settings → Networking → Generate Domain. Esa URL va en el QR y en el Atajo (`POST /api/biometrics/atajo` con `AtajoPayload`).

**Reglas de operación:**
- Cada merge a `main` redespliega y corta unos segundos (hay volumen). **El domingo, después de las 8:45, nadie pushea.**
- `POST /admin/snapshot` copia la base a `DATA_DIR/snapshot.db` (en el volumen, sobrevive al redeploy) justo antes de la caída en vivo; `POST /admin/restore` la vuelve a copiar entre ensayos.
- Los límites del trial: US$5 y volumen de 0,5 GB. Alcanza para la base y los audios, **no** para el modelo de `faster-whisper`: la transcripción va por la API de OpenAI.
- Revisar el consumo de Railway y de la API de Claude en cada checkpoint.

**Plan B:** si Railway falla, el mismo proceso corre en una laptop con `cloudflared tunnel` (da HTTPS). Solo como emergencia: el traslado de las 21 lo corta. Ojo: el Atajo y las suscripciones push apuntan al dominio de Railway; con el plan B hay que volver a suscribirse.

---

## 10. Desarrollo local y trabajo en paralelo

- Cada uno corre `uvicorn app.main:app --reload` con su `.env` y su base en `./data`. Nadie toca la base de Railway desde su laptop.
- Ramas por persona, PRs chicos, `main` siempre corre. Para dos sesiones de Claude Code en paralelo, **git worktrees** (una rama por sesión).
- Mientras la pieza de otro no existe, se trabaja contra datos falsos con la forma del contrato (por ejemplo, la vista del informe con un JSON de `Report` inventado).

**CI** (`.github/workflows/tests.yml`):
```yaml
name: tests
on: [pull_request, push]
jobs:
  test:
    runs-on: ubuntu-latest   # reemplazar por el label del runner de Tenki
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt pytest
      - run: pytest tests/rules -q
```

---

## 11. Herramientas de la hackathon

| Herramienta | Uso | Decisión |
|---|---|---|
| Claude API | Producto (Haiku para extraer y respaldo de rojos; Sonnet para explicar, preguntar e informe) + Claude Code para construir | Sí. Key compartida: vigilar consumo |
| Tenki Code Reviewer | Revisa cada PR, en especial los de `rules/` | Sí, sin bloquear un merge urgente |
| Tenki Runners | Corre el CI | Sí |
| Tenki Sandbox | Ejecutar código generado por un agente | No: el producto no lo necesita |
| Kiro | Specs, steering, hooks | No: CLAUDE.md ya es la spec. Quien quiera su IDE: symlink `AGENTS.md → CLAUDE.md` |
| Atajos de iOS | Mandar pasos de Salud a la API | Sí (viene con el iPhone) |
| Railway, OpenAI (Whisper) | No los da la hackathon | Sí |
| Twilio | WhatsApp | P2 |

---

## 12. Riesgos y planes B

| Riesgo | Plan B |
|---|---|
| La push no llega en un iPhone | El inicio muestra todo desde `notifications`; en la demo se abre la app |
| El micrófono no anda en modo app en iPhone | Escribir en vez de grabar: el resto del flujo es igual |
| El Atajo no corre solo (iOS pide confirmación) | En la demo se toca el Atajo a mano; la historia viene de la importación |
| La exportación de Salud no sirve | CSV de pasos por hora con el mismo formato (CLAUDE.md §8) |
| Jurado con Android | Funciona desde Chrome, con push incluso sin instalar |
| Transcripción falla o tarda | Escribir en vez de grabar |
| Railway cae | `cloudflared tunnel` desde una laptop (hay que volver a suscribir push y apuntar el Atajo) |
| Se agota la key de Claude | Haiku para todo lo posible; informe regenerado como máximo cada 30 s; revisar en cada checkpoint |
| Latencia alta en la extracción | Haiku + prompt caching de `knowledge/parkinson.md`; estados de carga en la app |
