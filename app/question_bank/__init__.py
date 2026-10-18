# Preguntas fijas (redacción propia). Se usan si la IA no pudo redactar la pregunta proactiva: es texto fijo,
# no se presenta como generado. Sin cifras ni términos clínicos, como las de pipeline.ask.
from app.models import QuestionText

_PROACTIVE = {
    "P-DESVIO": ("{name}, hoy caminaste menos que {baseline} después de la pastilla. ¿Pasó algo?",
                 ["Estaba duro", "Me sentí bien, solo no salí", "No me acuerdo"]),
    "P-NOCHES": ("¿Cómo vienen las noches de {patient} estos días?",
                 ["Se despierta mucho", "Duerme bastante bien", "No sabría decir"]),
    "P-SILENCIO": ("{name}, ¿cómo anduviste estos días?", ["Bien, como siempre", "Algo cansado", "Más o menos"]),
    "P-JUEGO": ("{name}, hoy el juego te salió más lento. ¿Cómo te sentís?",
                ["Igual que siempre", "Algo cansado", "Estaba duro"]),
    "P-REPITE": ("{name}, ¿cómo te sentiste estos días?", ["Bien", "Más o menos", "No me acuerdo"]),
}
_GENERIC = ("{name}, ¿cómo estás hoy?", ["Bien", "Más o menos", "No muy bien"])
# Desde las 04:15 los datos raros (pasos, pulsera, juego) se le preguntan a Marta: sobre Juan, en tercera persona.
_FAMILY = {
    "P-DESVIO": ("Notamos que {patient} caminó menos que {baseline}. ¿Pasó algo?",
                 ["Estaba duro", "Se quedó en casa", "No sé"]),
    "P-SUENO": ("¿Cómo pasó {patient} la noche?", ["Se despertó mucho", "Durmió bien", "No sabría decir"]),
    "P-JUEGO": ("Hoy el juego le salió más lento a {patient}. ¿Cómo lo ves?",
                ["Igual que siempre", "Algo cansado", "Estaba duro"]),
}


def proactive(rule_id: str, patient_name: str, recipient_role: str, *,
              baseline_label: str = "otras tardes") -> QuestionText:
    family = recipient_role != "paciente" and rule_id in _FAMILY
    template, options = _FAMILY[rule_id] if family else _PROACTIVE.get(rule_id, _GENERIC)
    name = patient_name if recipient_role == "paciente" else ""
    question = template.format(name=name, patient=patient_name, baseline=baseline_label).lstrip(", ").strip()
    i = 1 if question.startswith("¿") else 0
    return QuestionText(question=question[:i] + question[i].upper() + question[i + 1:], options=list(options))
