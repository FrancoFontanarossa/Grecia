# Entrecasa — sistema de diseño y pantallas

> Va en `design/DESIGN.md` del repo. Es la referencia visual para construir la PWA. CLAUDE.md §9 resume esto; si hay diferencia, **manda este archivo** para lo visual y CLAUDE.md para el comportamiento.
> `design/screens/*.html` son las pantallas del lienzo de diseño exportadas. Son HTML con estilos en línea: **copiar medidas, colores, textos y jerarquía de ahí**. La sintaxis `{{…}}`, `<sc-for>`, `<sc-if>` y `<x-dc>` es del editor de diseño: en Jinja se reemplaza por `{{ }}`, `{% for %}` y `{% if %}`; los estilos en línea se pueden pasar a clases usando las variables de `tokens.css`.
> Tokens listos para usar: `design/tokens.css` (variables CSS, sin build).

---

## 1. Dirección

**"Sereno y firme".** Una app que una persona de 74 años con temblor usa sin ayuda, y que su familia mira con calma. Nada clínico ni infantil: fondo verde grisáceo muy claro, un verde pino como único color de acción y azul solo para lo que mide el teléfono. Así se distingue de un vistazo **lo medido** (azul) de **lo contado** (texto) y de **lo que hay que hacer** (pino).

Prohibido: degradados, emoji, sombras decorativas, Inter/Roboto/Arial, texto gris claro sobre blanco, íconos solos sin palabra en acciones de Juan.

---

## 2. Tokens

### Color
| Token | Hex | Uso |
|---|---|---|
| `fondo` | `#F2F4F1` | Fondo de todas las pantallas |
| `superficie` | `#FFFFFF` | Tarjetas |
| `superficie-suave` | `#E8ECE9` | Notas al pie ("Lo último que anotamos") |
| `linea` | `#D5DBD6` | Bordes de tarjetas y botones secundarios inactivos |
| `linea-suave` | `#E3E8E4` | Separadores dentro de tarjetas |
| `tinta` | `#17201B` | Texto principal |
| `tinta-suave` | `#4A5650` | Texto secundario (cumple 4,5:1 sobre blanco y fondo) |
| `pino` | `#1E5B4F` | Acción principal, botón de voz, seleccionado |
| `pino-claro` | `#DCEBE6` | Halo del botón de voz, fondos de acción, carril verde |
| `pino-oscuro` | `#123A32` | Fondo de la pantalla "Grabando" |
| `pino-texto-claro` | `#B9D3CB` | Texto secundario sobre pino oscuro |
| `bio` | `#2F5FA8` | Datos del teléfono (pasos, juego hoy) |
| `bio-medio` | `#9DB6DD` | Barras de días normales |
| `bio-suave` | `#C9D7EC` | Barras "no llegó a la meta" / historial |
| `bio-claro` | `#E1EAF7` | Fondo de anillos y chips de dato |
| `bio-texto` | `#1D3F73` | Texto sobre `bio-claro` |
| `ambar` | `#B45309` | Barras de episodio, ícono ámbar |
| `ambar-fondo` | `#FCEFD9` | Tarjeta ámbar |
| `ambar-texto` | `#8A3F06` | Texto y etiqueta sobre ámbar |
| `rojo` | `#B42318` | Rojo, botón de detener grabación |
| `rojo-fondo` | `#FDE4E1` | Pantalla/etiqueta roja |

### Tipografía
**Atkinson Hyperlegible** (Google Fonts, 400, 700, 400 itálica). Una sola familia. Diseñada por el Braille Institute para baja visión.

| Rol | Juan | Familia | Neuróloga |
|---|---|---|---|
| Título de pantalla | 32–34 / 700 | 28 / 700 | 24 / 700 |
| Texto principal | 21–22 / 400 | 18–19 / 400 | 16–17 / 400 |
| Secundario | 18 / 400 `tinta-suave` | 16 / 400 | 15 / 400 |
| Mínimo absoluto | 16 | 14 | 13 |
| Interlineado | 1,35–1,45 | 1,4–1,45 | 1,5–1,6 en párrafos del informe |

Etiquetas de sección en mayúsculas: 14 / 700, `letter-spacing: 1px`, `tinta-suave`.

### Espaciado, radios y tamaños
- Margen lateral del teléfono: 24 (Juan), 20 (familia). Arriba: 56–60 (sin barra de estado falsa; respetar `env(safe-area-inset-top)`).
- Separación entre bloques: 16–22. Dentro de tarjetas: 8–12.
- Radios: tarjeta 20, botón principal 20–22, botón secundario 18, chip 10–14, píldora 999.
- **Botones de Juan: alto mínimo 64; principal 72–76.** Familia: 56–68. Neuróloga: 44.
- Botón de voz de Juan: círculo de 188 con halo de 14 en `pino-claro`. Grabando: círculo blanco de 168 con cuadrado rojo de 52 y dos halos blancos al 14% y 6%.
- Íconos de trazo 2 px (lucide o equivalente): 22–30 en botones, 18 en etiquetas, 72 en el botón de voz.

---

## 3. Componentes

| Componente | Especificación |
|---|---|
| `VoiceButton` | Círculo `pino`, ícono micrófono blanco, halo `pino-claro`. Debajo, título 26/700 y ayuda 18 `tinta-suave` ("Tocá una vez para hablar"). **Tocar = empezar; tocar de nuevo = terminar.** Nunca mantener apretado. `aria-label="Contame cómo estás"`. |
| `PrimaryButton` | Fondo `pino`, texto blanco 20–22/700, radio 20–22, alto 68–76, ícono opcional a la izquierda. |
| `SecondaryButton` | Fondo blanco, borde 2 px `pino`, texto `tinta` 20–21/400, mismas medidas. |
| `QuickReply` | Botón a lo ancho, alto 64, borde 2 `pino`, texto 21 alineado a la izquierda. Seleccionado: fondo `pino`, texto blanco. |
| `Card` | Fondo blanco, radio 20, padding 16–22, sin sombra. |
| `LaneChip` | Píldora con ícono + palabra. Rojo: `rojo-fondo`/`rojo`, triángulo, "Rojo · actuar ahora". Ámbar: `ambar-fondo`/`ambar-texto`, círculo con !, "Ámbar · para mirar". Verde: `pino-claro`/`pino`, check, "Verde · en orden". **Nunca solo color.** |
| `EvidenceChip` | Enlace chico (14) con borde `#C9D1CB` y radio 10: "Marta · mié 21:40". Dato del teléfono: fondo `bio-claro`, texto `bio-texto`. Abre el relato o la serie. |
| `StepsRing` | Anillo de 80, trazo 9, fondo `bio-claro`, progreso `bio`, porcentaje 18/700 al centro. Debajo: "2.840 pasos" 20/700 y "Tu meta: 4.000" 16. |
| `CompareBars` | "Por qué te pregunto": dos filas, etiqueta a la izquierda y cifra 700 a la derecha; barra de 14 de alto con fondo `bio-claro`. Habitual en `bio-medio` al 100%; hoy en `bio` proporcional. Pie: "Medido por tu teléfono. No es un diagnóstico." |
| `WeekBars` | 7 barras con día debajo (13). Llegó a la meta: `bio`; no llegó: `bio-suave`. Leyenda con cuadraditos de 12. |
| `UnderstoodCard` | "Anoté esto": tarjeta con metadato arriba (15 `tinta-suave`: "Hoy, 16:40 · Movimiento") y la frase `plain` del evento (21, interlineado 1,35). |
| `Note` | Fondo `superficie-suave`, radio 16, ícono pino + texto 16–17. |
| `ReservedToggle` | `<label>` con checkbox de 26 (`accent-color: pino`), título 17/700 "Solo lo ve el equipo médico." y ayuda 14 "Juan no recibe nada de esto." |
| `Avatar` | Círculo de 60 con inicial 26/700. Juan: `pino`/blanco. Marta: `pino-claro`/`pino`. Laura: `bio-claro`/`bio-texto`. |
| `Logo` | Cuadrado redondeado `pino` (radio 12–16) con casa de trazo blanco + "entrecasa" en minúscula 26–36/700, `letter-spacing: -0.3px`. |

---

## 4. Pantallas (P0)

`/casa` muestra el inicio según el rol guardado en el teléfono (Juan, Marta o Laura). Las rutas son las de `docs/ARQUITECTURA.md`.

Cada pantalla en `design/screens/`. Tamaño de referencia del teléfono: 390 × 844.

### `/` · ¿Quién sos? — `Selector.html`
Logo · "¿Quién sos?" 34 · "Elegilo una vez. Este teléfono se va a acordar." · tres tarjetas-enlace de 96 de alto (avatar, nombre 24/700, relación 16, chevron): Juan (borde `pino`), Marta, Laura · abajo, botón secundario "Soy del equipo médico" · pie 14: "Demo: sin contraseña…". Al elegir: guardar `person_id` en `localStorage`, pedir permiso de notificaciones **con un botón** ("Activar avisos") y registrar la suscripción.

### `/casa` (Juan) · Inicio — `Juan-Inicio.html`
Fecha 18 · "Buenas tardes, Juan" 34 · `VoiceButton` · dos tarjetas en grilla: `StepsRing` y "Próxima toma 20:00" (28/700) · fila-enlace "Juego de 20 segundos / Hoy todavía no lo hiciste" (alto 72) · `Note` al pie: "Lo último que anotamos: …". Si hay `pending_question`, la tarjeta de la pregunta reemplaza a la fila del juego. Datos: `GET /api/hoy/{person_id}`.

### `/casa/pregunta/{question_id}` · Pregunta (abre desde el push) — `Juan-Pregunta.html`
Píldora "Una pregunta de hoy" + enlace "Ahora no" · pregunta 30/700 (texto de `pipeline.ask`) · tarjeta "Por qué te pregunto" con `CompareBars` (cifras del código) · 3 `QuickReply` (opciones de `pipeline.ask`) · abajo, `PrimaryButton` con micrófono "Contalo con tu voz". Responder → `POST /api/entries` con `question_id` y `quick_reply` → "Anoté esto".

### `/casa/contar` (Juan) · Grabando — `Juan-Grabando.html`
Fondo `pino-oscuro`. "Te escucho" 18 · "Contá con tus palabras. Si pasó otro día, decí cuándo." 26/700 · contador 44/700 · onda de 28 barras de 6 px (`#7FB5A6`, alto según el volumen real del micrófono) · botón de detener · "Tocá para terminar" 22/700 · "Cancelar". Al terminar: estados de progreso (§5) sobre este mismo fondo.

### `/casa/anote/{entry_id}` · Anoté esto — `Juan-Anote.html`
Check en círculo `pino` de 64 · "Gracias, Juan. Anoté esto:" 32 · una `UnderstoodCard` por evento (`understood[]`) · `Note`: "Lo va a ver la Dra. Pereira en el resumen para tu consulta del 28 de octubre." · "¿Está bien así?" · grilla de dos botones: "Corregir" (secundario) y "Sí, está bien" (principal).

### `/casa/golpeteo` · Juego de golpeteo — `Juan-Juego.html` (interactivo)
Tres estados en la misma pantalla:
- **Listo:** instrucción 30/700 "Tocá los dos círculos, uno y otro, lo más rápido que puedas." + ayuda + dos círculos de 120 en `pino-claro` + "Empezar".
- **Jugando:** "Quedan 20" y "Toques N" (48/700) · dos botones circulares de 150; **el que hay que tocar está en `pino`**, el otro en `pino-claro` · un toque solo cuenta si alterna. Guardar `{t_ms, side}` de cada toque con `performance.now()`.
- **Listo:** "¡Listo, Juan!" · tarjeta "Hoy · X,X toques por segundo" · tarjeta "Tus últimas veces" con 7 barras (hoy en `bio`, anteriores en `bio-suave`) y el veredicto del backend · "Otra vez" / "Terminar".
Puntaje siempre en el backend (`POST /api/tests`). El texto nunca dice "diagnóstico" salvo para negarlo.

### `/casa` (Marta) · Hoy — `Marta-Hoy.html`
Fecha · "Hola, Marta" 28 · tarjeta ámbar (`LaneChip` ámbar, hecho 19/700, "Qué podés hacer:" 16, `EvidenceChip`s) · tarjeta "La semana de Juan" con `WeekBars` y una línea de resumen · fila de logro en `pino-claro` con ícono de copa · abajo, grilla 2:1 "Contar algo" (principal con micrófono) y "Escribir" (secundario). Datos: `GET /api/hoy/{person_id}`, consulta cada 3 s.

### `/casa/contar` (familia) · Contar algo — `Familia-Cargar.html`
Volver + "Contar algo de Juan" 26 · "¿Cuándo pasó?" con chips de 48 (Hoy · Anoche · Esta semana · Otro día…; seleccionado en `pino`) · ayuda 14 · al grabar: tarjeta "Lo que dijiste" (transcripción 18) y tarjeta "Lo que entendimos" (chips con `plain`) · `ReservedToggle` · grilla 1:2 "Regrabar" / "Guardar".

### `/casa` (Laura) · Resumen — `Laura-Resumen.html`
"Desde Salto" · "Papá esta semana" 28 · tarjeta `pino` con el último logro (22/700 blanco) y botón blanco "Mandale un audio" (P1: si no está, se oculta) · tarjeta con tres filas (ícono en cuadrado de 44 + texto 17): meta de pasos, noches, cuántas veces contaron · `Note` con la próxima consulta · pie: "Te avisamos de logros y de cualquier rojo. El resto, en este resumen." Laura nunca ve lo reservado.

### `/neuro/informe/{patient_id}` · Informe (computadora, página fluida) — `Medico-Informe.html`
Ancho máximo 1200, se apila en pantallas chicas. Encabezado (paciente, período, consulta) + "Vista técnica" e "Imprimir" · chips de medicación (el cambio de pramipexol en ámbar con "hace N días") y fuentes · **tarjeta "Resumen de las 4 semanas" con un párrafo de prosa 18/1,6** (`report.summary`) · gráfico de pasos por día 4 semanas (barras `bio-medio`, episodios en `ambar`, línea negra en el cambio de medicación) · columna principal "3 temas para esta consulta": cada tema con título 22/700, etiquetas, **párrafo redactado** (`narrative`), voces lado a lado en tarjetas `fondo`, `EvidenceChip`s y "Pregunta sugerida" en `pino-claro` · columna lateral "Datos del teléfono" (promedio, días en meta, golpeteo), "Alertas del período" y la nota de verificación ("Cada cifra se verificó contra los datos: N frases eliminadas… No es un diagnóstico."). Temas reservados con la etiqueta "Para hablar en privado".

### `/casa/emergencia/{alert_id}` (no está en el lienzo)
Fondo `rojo-fondo`, `LaneChip` rojo, texto fijo de la regla en 24/700 `tinta`, pasos numerados en 21, botón principal rojo con el número de emergencia, y "Entrecasa no es un servicio de emergencias" al pie.

---

## 5. Estados (lo pide la rúbrica)

| Momento | Texto | Visual |
|---|---|---|
| Subiendo/transcribiendo | "Pasando a texto…" | Onda quieta + indicador circular `pino` |
| Extrayendo | "Entendiendo lo que contaste…" | Mismo indicador |
| > 15 s | "Está tardando un poco más. No cierres la app." | Igual |
| Audio vacío o ininteligible | "No te escuché bien. ¿Probamos de nuevo?" | Botón "Probar de nuevo" |
| Sin permiso de micrófono | "Necesito permiso para escucharte. Abrí Ajustes › Safari › Micrófono." | Botón "Escribir en vez de hablar" |
| Sin conexión | "No hay conexión. Probá de nuevo en un rato." | — |
| Falla la IA | "No pude entenderlo esta vez. Lo guardé tal cual para tu neuróloga." | Igual se muestra la transcripción |
| Sin datos | "Todavía no hay datos de esta semana." | Tarjeta vacía con el mismo tamaño |
| Push desactivado | "Activá los avisos para que te podamos preguntar." | Botón "Activar avisos" |

Copy: rioplatense, de "vos", frases cortas, nunca culpa, nunca jerga médica para Juan y la familia.

---

## 6. Notificaciones push

| Para | Título | Cuerpo | Abre |
|---|---|---|---|
| Juan, pregunta | "Juan, una pregunta de hoy" | la pregunta de `pipeline.ask` | `/casa/pregunta/{id}` |
| Marta, ámbar | "Algo para mirar" | una línea sin detalle clínico | `/casa` |
| Laura/Marta, logro | "Juan llegó a su meta" | "4.060 pasos hoy." (cifras del código) | `/casa` |
| Familia, rojo | "Rojo · Juan" | texto fijo de la regla | `/casa/emergencia/{id}` |

Nunca se manda contenido reservado en el cuerpo de una notificación (se ve en la pantalla bloqueada).
