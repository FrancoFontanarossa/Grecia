# Preguntas fijas (redacción propia). Se usan si la IA no pudo redactar la pregunta proactiva: es texto fijo,
# no se presenta como generado. Sin cifras ni términos clínicos, como las de pipeline.ask.
from app.models import QuestionText

_PROACTIVE = {
    "P-DESVIO": ("{name}, hoy caminaste menos que otros días después de la pastilla. ¿Pasó algo?",
                 ["Estaba duro", "Me sentí bien, solo no salí", "No me acuerdo"]),
    "P-NOCHES": ("¿Cómo vienen las noches de {patient} estos días?",
                 ["Se despierta mucho", "Duerme bastante bien", "No sabría decir"]),
    "P-SILENCIO": ("{name}, ¿cómo anduviste estos días?", ["Bien, como siempre", "Algo cansado", "Más o menos"]),
    "P-JUEGO": ("{name}, hoy el juego te salió más lento. ¿Cómo te sentís?",
                ["Igual que siempre", "Algo cansado", "Estaba duro"]),
    "P-REPITE": ("{name}, ¿cómo te sentiste estos días?", ["Bien", "Más o menos", "No me acuerdo"]),
}
_GENERIC = ("{name}, ¿cómo estás hoy?", ["Bien", "Más o menos", "No muy bien"])


def proactive(rule_id: str, patient_name: str, recipient_role: str) -> QuestionText:
    template, options = _PROACTIVE.get(rule_id, _GENERIC)
    name = patient_name if recipient_role == "paciente" else ""
    question = template.format(name=name, patient=patient_name).lstrip(", ").strip()
    i = 1 if question.startswith("¿") else 0
    return QuestionText(question=question[:i] + question[i].upper() + question[i + 1:], options=list(options))
