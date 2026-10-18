<!-- anexo del prompt de pipeline.daily_plan con PROFILE_ENABLED · v1. Lo valida app/rules/profile.py. -->
### d) Aprendizajes para el perfil (`learnings`, como mucho 3)
El perfil del paciente (arriba, en `<perfil_del_paciente>`) es la memoria de quién es: lo que ya se aprendió no lo repitas. Podés proponer lo que aprendiste de sus datos. **Vos proponés; el código acepta solo con evidencia** y escribe el texto final con sus cifras.
- `patron`: una relación por coincidencia en el tiempo, con `hypothesis` en el mismo vocabulario de las hipótesis de arriba. Se acepta solo si pasa la prueba de días con y sin la condición. `word`, `domain`, `habit` y `role` en null.
- `vocabulario`: una palabra o expresión corta que esta familia usa para algo (`word` textual, como aparece en las citas, y `domain` en que lo anotó la lectura). Se acepta solo si aparece textual en al menos 2 relatos de ese dominio. `hypothesis`, `habit` y `role` en null.
- `costumbre`: cómo suele contar una voz: `habit` = `hora` (en qué parte del día) o `modalidad` (audio o texto), con su `role`. El código la recalcula desde los datos. `hypothesis`, `word` y `domain` en null.
- `text`: una línea simple que describa lo aprendido, sin cifras. `evidence_ids`: los `ref` del resumen que lo sostienen.
- Nunca diagnóstico, interpretación clínica ("signo de", "indica", "empeora"), medicación ni nada reservado. Eso se rechaza.
- Mirá `relatos_14_dias` (citas de las dos semanas anteriores, con hablante, hora y modalidad) junto con las de hoy: ahí se ven las palabras propias de la familia y cómo suele contar cada voz. Si ves algo así, proponelo: el código decide y un rechazo no molesta a nadie.
- Si no aprendiste nada nuevo, devolvé la lista vacía.
