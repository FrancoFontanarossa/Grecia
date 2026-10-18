# Eval de Entrecasa (CLAUDE.md §13)

Corrida: 18/10/2026 00:07 · extracción `claude-haiku-5-5`, ask e informe `claude-sonnet-5-5` · 30 relatos etiquetados por Franco.

| Qué | Resultado | Meta |
|---|---|---|
| Relatos · Dominio | Claude 100% (32/32) [89–100] · sin IA 59% (19/32) [42–74] | Claude > sin IA |
| Relatos · Hablante | Claude 100% (30/30) [89–100] · sin IA 60% (18/30) [42–75] | Claude > sin IA |
| Relatos · Negación | Claude 100% (30/30) [89–100] · sin IA 60% (18/30) [42–75] | Claude > sin IA |
| Relatos · Atribución ajena | Claude 93% (28/30) [79–98] · sin IA 47% (14/30) [30–64] | Claude > sin IA |
| Relatos · Hora | Claude 77% (23/30) [59–88] · sin IA 33% (10/30) [19–51] | Claude > sin IA |
| Relatos · eventos de más | Claude 8 · sin IA 2 | — |
| Rojos · recall | Reglas 100% (15/15) · reglas + Haiku 100% (15/15) | 100% |
| Rojos · falsos rojos | Reglas 0% (0/15) · reglas + Haiku 0% (0/15) | se reporta |
| Límites · cebos bloqueados y respondidos | 100% (10/10) (texto fijo 100% (10/10) · IA sin recomendar 100% (10/10)) | 100% |
| Canal reservado · filtraciones hacia Juan | 0 en 83 combinaciones | 0 |
| Informe · generados | 0% (0/5) | se reporta |
| Informe · cifras iguales al código (0 informes) | — (antes del verificador —) | 100% |
| Informe · citas idénticas | — (antes —) | 100% |
| Informe · frases borradas por el verificador | 0 | se reporta |
| Acuerdo Franco–Juanpe (techo) | pendiente: juanpe.jsonl sin etiquetas | se reporta |

## Definiciones

Se fijaron antes de la segunda etiqueta y valen para las dos (Franco y Juanpe).

- **Atribución ajena**: cualquier causa que quien habla le atribuye al síntoma (edad, cansancio, medicación, nervios, calor…). Se puntúa si se detectó, no el texto exacto.
- **Hora**: anoche · hoy · ayer · **vago** (referencia imprecisa —"el otro día", "últimamente", "desde que…", un día que no es hoy ni ayer— o un hábito sin fecha: "siempre que…", "todas las tardes") · **ninguna** (sin ninguna referencia de tiempo). Los relatos se cargan el miércoles 14/10 a las 14:00.
- **Eventos**: dos si son dos síntomas distintos; uno si es el mismo síntoma contado dos veces; ninguno si no hay síntomas.

IC 95% de Wilson entre corchetes. "Sin IA" = búsqueda por palabras sobre la taxonomía + negación por reglas (`eval/baseline_lexico.py`).

Notas:
- Informe del 13/10 no generado (el validador del código lo rechazó dos veces): redactar_informe no validó después de 2 intentos: resumen: el número '3' no está en facts
- Informe del 14/10 no generado (el validador del código lo rechazó dos veces): redactar_informe no validó después de 2 intentos: «Mañanas difíciles el 12/10 y el 13/10»: pone una franja (manana) que no está en los eventos
- Informe del 15/10 no generado (el validador del código lo rechazó dos veces): redactar_informe no validó después de 2 intentos: resumen: el número '1' no está en facts
- Informe del 16/10 no generado (el validador del código lo rechazó dos veces): redactar_informe no validó después de 2 intentos: resumen: el número '1' no está en facts
- Informe del 17/10 no generado (el validador del código lo rechazó dos veces): redactar_informe no validó después de 2 intentos: «Noches cortadas y días de pocos pasos» nombra la noche pero incluye eventos de otra franja: [27, 28]
