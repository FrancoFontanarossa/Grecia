import os
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Montevideo")

# Todo lo persistente va en el volumen de Railway (ARQUITECTURA §4.2).
DATA_DIR = Path(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH") or "./data")

# Paciente al que van los pasos del Atajo (un solo ATAJO_TOKEN, el de Juan en el seed).
ATAJO_PATIENT_ID = 1

# Desvío de pasos después de una toma (CLAUDE.md §7.3).
DEVIATION_WINDOW_MINUTES = 120   # x = pasos de 0 a 120 min después de la toma
DEVIATION_BASELINE_DAYS = 28     # días previos para la línea de base
DEVIATION_MIN_POINTS = 10        # mínimo por estrato; si no, base combinada; si tampoco, None
DEVIATION_MAD_SCALE = 1.4826     # z = (x − mediana) / (1,4826 · MAD)
DEVIATION_MAD_FLOOR = 0.10       # MAD como mínimo el 10% de la mediana
DEVIATION_Z_MAX = -2.5           # hay desvío si z ≤ −2,5…
DEVIATION_MIN_DROP = 0.40        # …y la caída es de al menos 40%

# Disparadores proactivos (CLAUDE.md §6.2).
NIGHTS_COUNT, NIGHTS_WINDOW_DAYS = 3, 7          # P-NOCHES: 3 noches con despertares en 7 días
SILENCE_DAYS = 2                                 # P-SILENCIO: 2 días sin relatos de ninguna voz
GAME_HISTORY, GAME_MIN_HISTORY = 7, 3            # P-JUEGO y games.score: últimas 7 sesiones, mínimo 3
GAME_SLOWER_RATIO = 0.85                         # …más lento si toques/s < 85% de la mediana
REPEAT_COUNT, REPEAT_WINDOW_DAYS = 2, 7          # P-REPITE: 2 veces en 7 días por la familia
# Pulsera (CLAUDE.md §8). Centrales: las manda el simulador. Opcionales: la ingesta las acepta y guarda si llegan.
# Temblor y discinesia se aceptan pero no se resumen ni se muestran (requieren algoritmos validados).
WEARABLE_CORE = ("sleep_minutes", "sleep_awakenings", "heart_rate_rest", "active_minutes")
WEARABLE_OPTIONAL = ("hrv_ms", "spo2_pct", "resp_rate", "tremor_minutes", "dyskinesia_minutes",
                     "walking_speed", "walking_asymmetry", "double_support", "steadiness")
WEARABLE_NOT_SHOWN = ("tremor_minutes", "dyskinesia_minutes")
SLEEP_TRIGGER_HOURS = (8, 12)                    # P-SUENO: a la mañana, de 8 a 12 (la noche que pasó)
SLEEP_TRIGGER_KINDS = ("sleep_awakenings", "sleep_minutes")   # …si la pulsera vio despertares o poco sueño

# Avisos ámbar (CLAUDE.md §6.3).
MED_CHANGE_WEEKS = 8                             # A2: primera mención dentro de las 8 semanas del cambio
EPISODES_COUNT, EPISODES_WINDOW_DAYS = 3, 7      # A3: 3 episodios en 7 días en el mismo tramo

# Claves de síntomas que usan las reglas. ALINEAR CON TAXONOMY DE GUADA (app/taxonomy.py en guada/ia).
SYMPTOMS_NIGHT_WAKINGS = {"despertares_nocturnos", "insomnio"}   # P-NOCHES
SYMPTOMS_A1 = {"alucinaciones", "delirios"}                      # A1: alucinación o delirio nuevo

# Modelos (CLAUDE.md §7.4)
# Modo 2: plan diario (pipeline.daily_plan + rules.plan). Apagado salvo DAILY_PLAN_ENABLED=1.
DAILY_PLAN_ENABLED = os.environ.get("DAILY_PLAN_ENABLED", "0") == "1"
DAILY_PLAN_HOUR = 21                             # a las 21 de clock.now() se planifica el día siguiente
DAILY_PLAN_WINDOW_DAYS = 28                      # ventana de las hipótesis
DAILY_MAX_QUESTIONS = 1                          # Juan: como mucho 1 pregunta (o seguimiento) planificada por día
DAILY_MAX_GAME_INVITES = 1                       # …y 1 invitación al golpeteo
# Bitácora de la revisión diaria: la nota de cada noche (solo equipo médico). BITACORA_ENABLED=0 la apaga en el
# precorrido y en el informe (la revisión en vivo sigue detrás de DAILY_PLAN_ENABLED).
BITACORA_ENABLED = os.environ.get("BITACORA_ENABLED", "1") == "1"
BITACORA_MEMORY_DAYS = 7                         # el digest trae las notas de los 7 días previos
PLAN_HOURS = ("08:00", "22:00")                  # las acciones van entre estas horas de mañana
HYPOTHESIS_MIN_DAYS = 4                          # días con y sin la condición, como mínimo
HYPOTHESIS_MIN_DIFF = 0.20                       # diferencia entre medianas, en la dirección declarada

MODEL_EXTRACT = "claude-haiku-5-5"
MODEL_REASON = "claude-sonnet-5-5"   # explain, ask, report
