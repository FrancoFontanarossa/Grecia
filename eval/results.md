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
| Informe · generados ¹ | 100% (5/5), cada uno con 3 temas | se reporta |
| Informe · cifras iguales al código ¹ | 100%: 0 frases borradas por cifras en 5 informes | 100% |
| Informe · citas idénticas ¹ | 100%: 0 frases borradas por citas en 5 informes | 100% |
| Informe · frases borradas por el verificador ¹ | 0 en 5 informes (0 reglas rechazadas por el código) | se reporta |
| Acuerdo entre etiquetadores (techo) | no medido: una sola etiqueta | se reporta |

Set chico (30 relatos) escrito y etiquetado por el equipo; se compara contra una búsqueda por palabras. Etiquetado por una persona.

¹ Filas del informe de la corrida v2 (`eval/informe.py`, 17/10/2026 21:25, `claude-sonnet-5-5`, main b403b73 + #37): 5 informes del escenario (cierre del martes 13 al sábado 17) por `pipeline.report.generate`, como en producción. El verificador borra cada frase con una cifra que no está en los datos del código o una cita que no existe carácter por carácter; en esta corrida no borró ninguna. Detalle y comparación con la corrida anterior en `eval/results_informe_v2.md`.

## Definiciones

Se fijaron antes de la segunda etiqueta y valen para las dos (Franco y Juanpe).

- **Atribución ajena**: cualquier causa que quien habla le atribuye al síntoma (edad, cansancio, medicación, nervios, calor…). Se puntúa si se detectó, no el texto exacto.
- **Hora**: anoche · hoy · ayer · **vago** (referencia imprecisa —"el otro día", "últimamente", "desde que…", un día que no es hoy ni ayer— o un hábito sin fecha: "siempre que…", "todas las tardes") · **ninguna** (sin ninguna referencia de tiempo). Los relatos se cargan el miércoles 14/10 a las 14:00.
- **Eventos**: dos si son dos síntomas distintos; uno si es el mismo síntoma contado dos veces; ninguno si no hay síntomas.

IC 95% de Wilson entre corchetes. "Sin IA" = búsqueda por palabras sobre la taxonomía + negación por reglas (`eval/baseline_lexico.py`).
