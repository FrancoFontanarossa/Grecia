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

# Avisos ámbar (CLAUDE.md §6.3).
MED_CHANGE_WEEKS = 8                             # A2: primera mención dentro de las 8 semanas del cambio
EPISODES_COUNT, EPISODES_WINDOW_DAYS = 3, 7      # A3: 3 episodios en 7 días en el mismo tramo

# Claves de síntomas que usan las reglas. ALINEAR CON TAXONOMY DE GUADA (app/taxonomy.py en guada/ia).
SYMPTOMS_NIGHT_WAKINGS = {"despertares_nocturnos", "insomnio"}   # P-NOCHES
SYMPTOMS_A1 = {"alucinaciones", "delirios"}                      # A1: alucinación o delirio nuevo
