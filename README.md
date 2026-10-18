# Entrecasa

Lo que pasa en casa entre una consulta y la otra, para una persona con Parkinson y su familia: medido por el teléfono (pasos del iPhone), contado por el paciente y su familia (audio o texto), preguntado cuando algo no cierra y llevado a la neuróloga en un informe que se lee en un minuto.
La IA entiende los relatos de varias voces, intenta explicar un desvío antes de molestar, redacta la pregunta y el informe; lo que no puede fallar (rojos, carriles, desvío, consentimiento, canal reservado, verificador) es código con tests.
No diagnostica, no estadifica, no infiere estado on/off y no recomienda medicación ni dosis. Proyecto de build 101; la especificación está en [CLAUDE.md](CLAUDE.md).

## Cómo correrlo

Requiere Python 3.12 y [uv](https://docs.astral.sh/uv/).

```bash
uv venv --python 3.12 .venv
uv pip install -r requirements.txt
cp .env.example .env               # completar las claves (ANTHROPIC_API_KEY, OPENAI_API_KEY, VAPID_*, ATAJO_TOKEN, ADMIN_TOKEN)
set -a; source .env; set +a

# Datos de la demo (en ./data, o en RAILWAY_VOLUME_MOUNT_PATH)
.venv/bin/python -m data.import_health ruta/a/export.xml --end 2026-10-17   # 4 semanas de pasos (o --csv pasos.csv)
.venv/bin/python -m data.seed                                               # personas, tomas, meta, golpeteo, caídas
.venv/bin/python -m scripts.precorrer_semana                                # relatos de la semana por el pipeline real

# App
.venv/bin/uvicorn app.main:app --reload       # http://localhost:8000

# Tests y eval
.venv/bin/pytest
.venv/bin/python eval/run.py                  # usa la IA real → eval/results.md
```

En Railway corre un solo proceso (`railway.toml`); la base se carga con `POST /admin/import_steps` y `POST /admin/seed` (ver [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md) §5 y §9).

## Declaración para la revisión técnica (CLAUDE.md §15)

| Pieza | Estado |
|---|---|
| Transcripción, extracción, explicación, preguntas e informe | **Funcional, IA real**: procesa entradas nuevas |
| Rojos, carriles, desvío, disparadores, consentimiento, juego, verificador | **Funcional, código con tests** |
| Pasos en vivo por el Atajo | **Funcional** (o por botón, si la automatización de iOS pide confirmación) |
| Historia de 4 semanas | **Real**: exportación de un integrante, fechas corridas |
| Caídas de pasos de la semana de Juan y la de la demo | **Inyectadas**, rotuladas (`source=inyectado`) |
| Relatos de lunes a viernes de Juan y Marta | **Escritos por el equipo**, procesados por el pipeline real con el reloj |
| Personas y neuróloga | **Ficticias** |
| Reloj | **Acelerado** en la demo |
| Roles sin login | **Mecanismo de demo** |
| Emergencias | **Nadie llama**; se muestra el texto fijo |
| Datos de pulsera (sueño, FC, HRV, SpO2, respiración, actividad, temblor, discinesia) | **Simulados**, rotulados (`source=simulado`) |
| Todo lo de P1 y P2 que no se construyó | **Pendiente**, se dice si preguntan |
