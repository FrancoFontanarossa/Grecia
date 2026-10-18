# Referencias de interfaz para Entrecasa

> Sábado 17/10/2026, 23:45 · investigación de Guada (con Claude) sobre 20 apps de salud, en tres grupos: apps para personas con una enfermedad crónica, servicios médicos B2C, y apps para mayores, cuidadores y médicos. Va en `design/REFERENCIAS.md`. **No reemplaza a DESIGN.md**: dice qué pulir dentro de los mismos tokens y por qué.

## La idea de marca: seriedad que no asusta

Las apps que mejor transmiten confianza clínica (el sistema de diseño del NHS, Apple Health, MyChart) no lo consiguen con decoración. Lo consiguen con **consistencia**: una tipografía, un color de acción, el mismo patrón de tarjeta en todas las vistas, y textos que dicen la conclusión primero y la ponen en proporción. El NHS lo resume como "tranquilizar, no asustar". Ese es el tono de Entrecasa. La regla práctica: **si un elemento no es un dato, una acción o una voz, se saca.**

Del otro extremo, las apps de enfermedad crónica más populares (mySugr, Bearable) usan mascotas, puntos, rachas, emoji y humor. Para alguien de 74 años con Parkinson, y frente a una neuróloga, eso resta seriedad. Lo descartamos a propósito. Un día malo es un dato para la neuróloga, no un fracaso para Juan.

La referencia más directa es **StrivePD** (Parkinson, autorización de la FDA): su informe "Top Concerns for your visit" es casi igual a nuestros "3 temas para esta consulta", y su check-in diario por voz valida el botón de voz. Lo que ellos no dicen, y nosotros sí, es que cada cifra del informe se verifica contra los datos.

## Cambios por pantalla

Prioridad: **A** = esta noche (visible en la demo, bajo riesgo). **B** = si sobra tiempo. Dueño entre paréntesis.

### Juan (inicio, grabando, pregunta, anoté esto)
- **A · Antirrebote del botón de voz** (Juanpe). Después de empezar a grabar, ignorar toques por 800 ms y contar el toque en `pointerdown`, aunque el dedo se deslice. Hoy un doble toque por temblor empieza y corta la grabación en el mismo segundo. No se aplica al juego de golpeteo, donde el toque crudo es el dato. *Ref: "Ignorar repetición" de las adaptaciones táctiles de iOS.*
- **A · Salida grande y siempre al pie** (Juanpe). El "Ahora no" de la pregunta y el "Cancelar" de grabando pasan a ser un botón secundario a lo ancho, de 64 de alto, siempre en el mismo lugar. *Ref: botón Atrás de Assistive Access.*
- **A · "Por qué te pregunto" con la conclusión primero** (Juanpe, texto del código). Una frase arriba ("Hoy a la tarde caminaste menos que de costumbre"), las dos barras (habitual en `bio-medio`, hoy en `bio`) con la cifra a la derecha, y el pie "Medido por tu teléfono. No es un diagnóstico." Siempre contra lo habitual de Juan, nunca contra otras personas. Queda visible, no plegado: en la demo es el diferencial. *Ref: Destacados de Apple Health; línea de base personal de Oura.*
- **A · "Anoté esto" acepta datos parciales** (ya está). "Sí, está bien" es la acción principal y "Corregir" la secundaria. Nunca se le piden campos a Juan. *Ref: Medisafe.*
- **B · Filas, no grilla.** Si las dos tarjetas del inicio (pasos y próxima toma) quedan apretadas en un teléfono chico, apilarlas. *Ref: maquetación en filas de Assistive Access.*
- **B · "Quién ve qué", visible en el inicio de Juan.** Una nota: "Laura ve tus pasos y tus logros. Lo que contás lo ve la Dra. Pereira." Consentimiento a la vista, no escondido en ajustes. *Ref: compartir datos de Salud de Apple.*

### Familia (Hoy de Marta, resumen de Laura)
- **A · Tarjeta ámbar: hecho, proporción, acción** (texto: Guada y Franco; tarjeta: Juanpe). Ejemplo: "Juan contó dos tardes de rigidez esta semana. Ya está en el resumen para la consulta del 28. Si se repite, podés llamar a la Dra. Pereira." Sin "deberías", sin interpretación clínica, con dos opciones como máximo. Título en palabras ("Algo para mirar"), y el ámbar nunca usa el triángulo del rojo. *Ref: guía de tono y care cards del NHS.*
- **A · El estado en una frase antes que el número.** "Esta semana, en orden" con su `LaneChip`, y después las cifras. *Ref: Propeller.*
- **B · Días en meta como 7 cuadraditos** en lugar de otro gráfico de barras. *Ref: grilla de íconos de Ada.*
- **Ya está bien:** a Laura solo le llegan logros y rojos; el cuerpo de la push lleva hechos y cifras sin adjetivos ("4.060 pasos hoy."), y "Mandale un audio" es el gesto de apoyo. *Ref: CaringBridge, Medisafe Medfriend.*

### Emergencia (pantalla roja)
- **A · El título dice la acción, no el estado** (Juanpe, texto de la regla: Franco). "Llamá ahora a la emergencia móvil si Juan…" en 24/700. El `LaneChip` rojo pasa a etiqueta secundaria. **Un solo botón**, con el número, y ningún otro enlace salvo el pie "Entrecasa no es un servicio de emergencias". Prefijo oculto "Acción inmediata:" para lectores de pantalla. *Ref: care card de emergencia del NHS (rojo con un bloque gris oscuro para distinguirla de todo lo demás).*

### Informe de la neuróloga y vista técnica
- **A · Una frase-conclusión arriba del gráfico de 4 semanas** (Juanpe con un dato del código). Ejemplo: "Promedió 4.654 pasos por día; 3 tardes por debajo de lo habitual después de la toma de las 16." La conclusión antes que la evidencia, también dentro de cada tema. *Ref: Destacados de Apple Health.*
- **A · Banda del rango habitual de Juan** detrás de las barras: P25 a P75 de sus propias 4 semanas, en `bio-claro`, con la línea del cambio de pramipexol encima. Referencia personal, nunca poblacional. *Ref: franja del PKG, percentiles del AGP de Dexcom, rango de mySugr.*
- **A · La verificación sube al resumen.** "Cada cifra se verificó contra los datos: N frases eliminadas. No es un diagnóstico." al pie de la tarjeta del resumen, no solo en la columna lateral. Es nuestro diferencial frente al informe con IA de StrivePD, que no lo declara.
- **A · "Alertas del período" en dos niveles, sin mezclar colores** (lógica: Franco; vista: Juanpe). Los rojos con su chip, la fecha y lo que se hizo. Los síntomas nuevos, agrupados en una sola línea en `tinta` con flecha, no 13 ámbar sueltos. La sugerencia a Juan ("¿Querés que le avisemos…?") no va en esta lista. *Ref: el NHS no usa care cards como advertencia; las tendencias de Apple Health no usan el color de alarma.*
- **Ya está bien:** orden fijo (encabezado, resumen, gráfico, 3 temas, columna de datos), tope de 3 temas, y evidencia clickeable que lleva a la frase original con nombre y hora. *Ref: StrivePD, Dexcom Clarity, MyChart.*
- **B · Una línea de "Mejor semana"** en la columna lateral, para que el informe no sea solo problemas. *Ref: "Mejor día" de Dexcom Clarity.*
- **B · "Día típico" en la vista técnica:** pasos por hora (mediana y banda) con líneas finas en cada horario de toma. *Ref: superposición de síntomas y tomas del PKG.*

### En todas las pantallas
- **A · Nunca solo color.** Revisar que cada estado (barras de episodio, días en meta, el círculo del juego que hay que tocar) tenga forma o palabra además del color. *Ref: declaración de accesibilidad de MyTherapy.*

## Lo que no copiamos
Mascotas, puntos, rachas que se rompen, emoji, humor, fondos oscuros tipo bienestar (Oura), alta densidad y personalización (Bearable), fotos de stock. Ninguna de las apps investigadas tiene premios de diseño confirmados; las tomamos por sus patrones, no por su prestigio.

## Fuentes
Archivos completos con las fuentes de cada afirmación: `r1-enfermedad-cronica.md` (StrivePD, Ada, MyTherapy, Medisafe, mySugr, Bearable, Propeller), `r2-servicios-medicos.md` (NHS, Apple Health, MyChart, Oura, One Medical, Function Health) y `r3-mayores-cuidadores-medicos.md` (Assistive Access, Jitterbug, Medisafe Medfriend, CaringBridge, Jointly, Dexcom Clarity, PKG). Lo que no se pudo verificar en esta ronda está marcado así en cada archivo.
