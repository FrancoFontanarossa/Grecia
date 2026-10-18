# Eval del informe (v2)

Corrida: 17/10/2026 21:25 · informe `claude-sonnet-5-5` · 5 informes del escenario (cierre de martes 13 a sábado 17) por `pipeline.report.generate`, como en producción.

## Después (main b403b73 + este PR, cambio de pramipexol al 03/10)

**Generados: 5 de 5** · objetivo: 5 de 5, cada uno con 3 temas y como mucho 1 frase borrada.

| Día | Generado | Temas | Frases borradas por verify_local | Reglas que el código rechazó (por intento) |
|---|---|---|---|---|
| 13/10 | sí | 3 | 0 | — |
| 14/10 | sí | 3 | 0 | — |
| 15/10 | sí | 3 | 0 | — |
| 16/10 | sí | 3 | 0 | — |
| 17/10 | sí | 3 | 0 | — |


## Antes de este cambio (main 357610c, con #30 y el cambio de pramipexol al 22/09)

Mismo script (`eval/informe.py`), antes de este PR. #30 ya hacía que se generaran 5 de 5, pero verify_local borraba
frases porque el número de tema de la frase privada ("tema 1") contaba como cifra suelta y las franjas del título
no cerraban.

| Día | Generado | Temas | Frases borradas por verify_local | Reglas que el código rechazó (por intento) |
|---|---|---|---|---|
| 13/10 | sí | 3 | 0 | — |
| 14/10 | sí | 3 | 6 | blanda: «Una mala noche y una mañana lenta» nombra la noche pero incluye eventos de otra franja: [26, 27, 1]<br>blanda: resumen: el número '2' no está en facts<br>blanda: resumen: el número '2' no está en facts |
| 15/10 | sí | 3 | 4 | blanda: resumen: el número '1' no está en facts<br>blanda: resumen: el número '1' no está en facts<br>dura: «Tema para hablar en privado» mezcla eventos reservados y no reservados |
| 16/10 | sí | 3 | 0 | blanda: resumen: el número '1' no está en facts |
| 17/10 | sí | 3 | 2 | blanda: resumen: el número '1' no está en facts<br>dura: «Alucinaciones e ideas que antes no estaban» mezcla eventos reservados y no reservados<br>blanda: resumen: el número '1' no está en facts |
