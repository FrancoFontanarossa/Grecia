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

# Modelos (CLAUDE.md §7.4)
MODEL_EXTRACT = "claude-haiku-5-5"
MODEL_REASON = "claude-sonnet-5-5"   # explain, ask, report
