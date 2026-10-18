# TEMPORAL: lo que todavía no está en app/rules/ de Franco. Rojos, carriles, consentimiento, presupuesto y
# disparadores ya vienen de app/rules/.

# ── Verificador del informe ────────────────────────────────────────────────────────────────────────────
# TEMPORAL: reemplazar por rules.verifier.verify de Franco (borra cifras y citas que no coinciden y las cuenta).

def verify_stub(report, facts: dict, sources: list) -> "object":
    """No borra nada: devuelve el informe tal cual con removed_count=0."""
    return report.model_copy(update={"removed_count": 0})
