# Dominios y síntomas normalizados (redacción propia; las escalas validadas solo como inspiración).
# Las reglas comparan por clave: normalize() lleva cualquier forma de decirlo a la clave canónica o a "otro".
import re
import unicodedata

from app.models import Domain

DOMAINS: dict[Domain, str] = {
    "motor": "Movimiento",
    "sueno": "Sueño y descanso",
    "neuropsiquiatrico": "Alucinaciones y confusión",
    "animo": "Ánimo",
    "cognitivo": "Memoria y atención",
    "autonomico": "Cuerpo",
    "dolor": "Dolor",
    "deglucion": "Tragar",
    "caidas": "Caídas",
    "impulsos": "Impulsos",
    "sexual": "Vida íntima",
    "otro": "Otro",
}

_BY_DOMAIN: dict[Domain, list[str]] = {
    "motor": ["temblor", "rigidez", "lentitud", "congelamiento", "movimientos_involuntarios",
              "dificultad_caminar", "voz_baja"],
    "sueno": ["despertares_nocturnos", "insomnio", "actua_suenos", "somnolencia_diurna",
              "piernas_inquietas", "cansancio"],
    "neuropsiquiatrico": ["alucinaciones", "delirios", "confusion"],
    "animo": ["tristeza", "ansiedad", "apatia", "irritabilidad"],
    "cognitivo": ["olvidos", "dificultad_concentracion", "desorientacion"],
    "autonomico": ["constipacion", "urinario", "mareo_al_pararse", "sudoracion", "babeo"],
    "dolor": ["dolor", "calambres"],
    "deglucion": ["atragantamiento", "dificultad_tragar"],
    "caidas": ["caida", "casi_caida"],
    "impulsos": ["juego_apuestas", "compras_compulsivas", "comer_compulsivo", "otros_impulsos"],
    "sexual": ["cambio_deseo_sexual"],
    "otro": ["otro"],
}

SYMPTOMS: dict[str, Domain] = {s: d for d, symptoms in _BY_DOMAIN.items() for s in symptoms}

# Formas comunes de decirlo (ya sin tildes y en minúscula) → clave. Se busca la frase más larga primero.
_SYNONYMS: dict[str, list[str]] = {
    "temblor": ["tiembla", "temblaba", "temblo", "temblando", "le tiembla la mano", "tiritaba"],
    "rigidez": ["duro", "dura", "estaba duro", "rigido", "rigida", "agarrotado", "trabado", "trabada",
                "tieso", "tiesa"],
    "lentitud": ["lento", "lenta", "le cuesta moverse", "todo le lleva mas tiempo", "bradicinesia"],
    "congelamiento": ["congelado", "se congelo", "se le pegan los pies", "se quedo clavado",
                      "no podia arrancar", "bloqueo al caminar"],
    "movimientos_involuntarios": ["discinesia", "discinesias", "se mueve solo", "movimientos raros",
                                  "se retuerce", "no para de moverse"],
    "dificultad_caminar": ["le cuesta caminar", "camina mal", "arrastra los pies", "pasitos cortos",
                           "inestable al caminar", "caminar"],
    "voz_baja": ["habla bajito", "no se le entiende", "voz baja", "voz debil", "habla muy bajo"],
    "despertares_nocturnos": ["se desperto", "se despierta", "despertares", "despertar", "desvelado de noche",
                              "se levanto varias veces", "noche mala", "mala noche", "durmio mal"],
    "insomnio": ["no durmio", "no puede dormir", "no pudo dormir", "no se duerme", "no pegue un ojo",
                 "no pego un ojo"],
    "actua_suenos": ["grita dormido", "pega patadas dormido", "se mueve dormido", "pesadillas",
                     "actua los suenos", "habla dormido", "pataleaba dormido"],
    "somnolencia_diurna": ["se duerme de dia", "dormido de dia", "somnoliento", "con sueno todo el dia",
                           "se queda dormido", "cabecea"],
    "piernas_inquietas": ["no puede quedarse quieto con las piernas", "inquietud en las piernas",
                          "piernas inquietas", "le hormiguean las piernas"],
    "cansancio": ["cansado", "cansada", "agotado", "agotada", "sin energia", "fatiga", "fatigado"],
    "alucinaciones": ["veia gente", "ve gente", "vio gente", "ve cosas", "veia cosas", "vio a alguien",
                      "hablaba con alguien que no estaba", "habla con gente que no esta",
                      "oye voces", "escucha voces", "ve animales", "alucina", "alucinacion"],
    "delirios": ["cree que le roban", "cree que lo engano", "piensa que lo engano", "desconfia de todos",
                 "cree que hay alguien en la casa", "celos", "paranoia", "delirio"],
    "confusion": ["confundido", "confundida", "no sabia donde estaba", "desorientado de golpe",
                  "estaba perdido", "decia cosas sin sentido"],
    "tristeza": ["triste", "bajoneado", "bajon", "llora", "lloro", "deprimido", "deprimida", "depresion"],
    "ansiedad": ["ansioso", "ansiosa", "nervioso", "nerviosa", "angustiado", "angustia", "preocupado"],
    "apatia": ["sin ganas", "no quiere hacer nada", "desganado", "le da todo igual", "apatico"],
    "irritabilidad": ["irritable", "enojado", "se enoja", "de mal humor", "mal humor", "rezonga"],
    "olvidos": ["se olvida", "se olvido", "olvido", "no se acuerda", "no se acordaba", "memoria"],
    "dificultad_concentracion": ["le cuesta concentrarse", "se distrae", "no sigue la conversacion",
                                 "pierde el hilo", "concentracion"],
    "desorientacion": ["desorientado", "desorientada", "no sabia que dia era", "se perdio",
                       "no reconocio la casa"],
    "constipacion": ["estrenido", "estrenida", "no va al bano", "no fue al bano", "estrenimiento"],
    "urinario": ["hace pis seguido", "se le escapa el pis", "se hizo pis", "orina", "pis de noche",
                 "incontinencia"],
    "mareo_al_pararse": ["se marea al pararse", "mareado al levantarse", "se marea", "mareo", "mareado",
                         "se le nubla la vista al pararse", "presion baja"],
    "sudoracion": ["transpira mucho", "suda mucho", "sudor", "transpiracion"],
    "babeo": ["babea", "se le cae la baba", "saliva", "baba"],
    "dolor": ["le duele", "me duele", "dolorido", "dolores"],
    "calambres": ["calambre", "se le acalambra", "contractura", "se le tuerce el pie", "distonia"],
    "atragantamiento": ["se atraganto", "se atraganta", "se ahogo con", "tos al comer", "se le fue por el otro lado"],
    "dificultad_tragar": ["le cuesta tragar", "no puede tragar", "no pudo tragar", "tragar", "pastillas no le bajan"],
    "caida": ["se cayo", "me cai", "cayo al piso", "lo encontre en el piso", "en el piso", "caerse", "cayo"],
    "casi_caida": ["casi se cae", "casi me caigo", "se tambaleo", "perdio el equilibrio", "se trastabillo"],
    "juego_apuestas": ["apuesta", "apuestas", "casino", "quiniela", "tragamonedas", "juega plata"],
    "compras_compulsivas": ["compra de mas", "compra cosas sin parar", "gasta mucho", "compras"],
    "comer_compulsivo": ["come sin parar", "come a escondidas", "atracones", "come dulces todo el tiempo"],
    "otros_impulsos": ["no se puede frenar", "impulsivo", "impulsiva", "obsesionado con"],
    "cambio_deseo_sexual": ["deseo sexual", "mas deseo", "menos deseo", "libido", "hipersexualidad"],
}


def _fold(text: str) -> str:
    """minúsculas, sin tildes, guiones bajos como espacios y espacios simples."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[_\-]+", " ", text.lower())
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text)).strip()


# Todas las formas (clave escrita con espacios + sinónimos) ordenadas de la más larga a la más corta.
_FORMS: list[tuple[str, str]] = sorted(
    [(_fold(key), key) for key in SYMPTOMS] + [(_fold(f), key) for key, forms in _SYNONYMS.items() for f in forms],
    key=lambda pair: len(pair[0]), reverse=True,
)


def normalize(symptom: str) -> str:
    """Clave canónica del síntoma, o "otro" si no se reconoce."""
    folded = _fold(symptom or "")
    if not folded:
        return "otro"
    key = folded.replace(" ", "_")
    if key in SYMPTOMS:
        return key
    for form, canonical in _FORMS:
        if re.search(rf"\b{re.escape(form)}\b", folded):
            return canonical
    return "otro"


def domain_of(symptom: str) -> Domain:
    return SYMPTOMS[normalize(symptom)]


def label(domain: str) -> str:
    """Etiqueta para la pantalla ("Movimiento", "Sueño y descanso"…)."""
    return DOMAINS.get(domain, DOMAINS["otro"])
