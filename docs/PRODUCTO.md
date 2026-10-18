# Entrecasa — producto y pitch

> **Versión 2.0** · sábado 17/10/2026, 17:30. Va en `docs/PRODUCTO.md` del repo. Lo que se construye está en `CLAUDE.md`; acá están el porqué, la competencia, el negocio y las preguntas del jurado.

## 1. El problema

El neurólogo ve a la persona con Parkinson cada 6 a 12 meses, unos minutos, y la ve como está ese día ([NICE NG71](https://www.nice.org.uk/guidance/ng71/chapter/Recommendations)). Lo que más pesa no aparece en ese rato. Entre el 31,8% (visión doble) y el 65,2% (delirios) de quienes tienen un síntoma no motor no se lo cuentan al equipo de salud ([Chaudhuri 2010](https://researchinnovation.kingston.ac.uk/en/publications/the-nondeclaration-of-nonmotor-symptoms-of-parkinsons-disease-to--2/), 242 pacientes). Sin una herramienta, en hasta el 40% de las consultas nadie pregunta por ellos ([King's College London](https://www.kcl.ac.uk/news/spotlight/treating-non-motor-symptoms-of-parkinsons)). La barrera principal no es la vergüenza: la gente no sabe que el síntoma tiene que ver con el Parkinson o que tiene tratamiento (Hurt 2019, 358 personas). Por eso la palanca es preguntar en el momento y llevarlo a la consulta.

Quien vive con el paciente ve lo que el paciente no ve. Los cuidadores reportan delirios en el 32% de los casos contra el 8% de los pacientes, y alucinaciones en el 51% contra el 23% ([Hermanowicz 2019](https://www.dovepress.com/impact-of-non-motor-symptoms-in-parkinsons-disease-a-pmdalliance-surve-peer-reviewed-article-NDT)). Salvedad que decimos: no son parejas paciente-cuidador y la muestra es autoseleccionada.

El registro suelto es ruidoso, pero el agregado de varios días es confiable: en el diario de Hauser el acuerdo por media hora es pobre (kappa 0,358) y los totales diarios son confiables (ICC 0,77 para tiempo en off) (Timpka 2022). Eso justifica un informe que agregue, no un diario crudo.

**La frase:** el médico ve a "otro paciente". Lo que pasa en casa no llega a la consulta, y la familia, que lo ve todo, no tiene canal.

### Un caso real (testimonio recogido el sábado 17/10)
Le contamos la idea a una chica cuyo abuelo murió con Parkinson. Lo cuidaba su tía abuela, que trabajaba de noche. Su abuelo se caía mucho y alguna vez pasó la noche entera en el piso sin que nadie se enterara. En la etapa avanzada tartamudeaba tanto que era muy difícil entender lo que pedía, y propuso algo simple: botones para lo básico (agua, baño). Es una sola historia y la contamos como tal, sin presentarla como dato. De ahí salen las siguientes etapas del producto: sugerir detección de caídas cuando se repiten y una botonera para cuando hablar cuesta (no se construyen este fin de semana).

## 2. Qué es y para quién

**Entrecasa es una app para el celular** que junta cuatro cosas: lo que mide el teléfono (pasos, comparados con la propia rutina de la persona y alineados a sus tomas), lo que cuentan el paciente y su familia (audio o texto, cuando quieran), **preguntas cuando algo no cierra** (con el motivo a la vista) y un juego de 20 segundos que mide la velocidad de los dedos. Todo termina en un informe que la neuróloga lee en un minuto.

| Actor | Qué vive hoy | Qué le da Entrecasa |
|---|---|---|
| Paciente (Juan, 74, iPhone, sin reloj) | Síntomas que naturaliza ("es la edad"), olvida o no relaciona | Un botón grande para contar, una pregunta por día como máximo con el porqué, y un juego corto |
| Familia en casa (Marta, esposa) | Ve todo, no tiene canal, no sabe qué es importante | Voz propia con permiso del paciente, "solo para el equipo médico" cuando hace falta, y qué hacer ante un aviso |
| Familia lejos (Laura, hija en Salto) | Se entera tarde y por teléfono | Logros, rojos y un resumen tranquilo de la semana |
| Neuróloga | 15 minutos, el paciente llega en un buen momento, diarios que no sirven | Un informe redactado con dos voces y evidencia, y los datos técnicos aparte |
| Prestador (mutualistas, prepagas, Hospital Británico) | Emergencias evitables, neurólogos saturados | Seguimiento entre consultas sin sumar personal (hipótesis a validar) |

**El caso concreto (antes / después).** Antes: Marta ve a Juan hablar de noche con alguien que no está, piensa que es el cansancio y no se lo dice a nadie; la consulta del 28 pasa sin que se hable. Después: lo cuenta en 20 segundos desde su celular, la app entiende que es una alucinación nueva a 11 días de un cambio de medicación, Juan no recibe nada que lo exponga, y el 28 la neuróloga lo tiene en el primer tema del informe, con la fecha, las palabras de Marta y una pregunta sugerida.

## 3. Competencia y diferencial

| | StrivePD (Rune Labs) | Kneu Health | PKG (Empatica) | **Entrecasa** |
|---|---|---|---|---|
| Sensor | iPhone; Apple Watch para el monitoreo pasivo (510(k) 2022) | Pruebas activas en el celular + Apple Watch (FDA, sep-2026) | Dispositivo de muñeca recetado por 6 días | **El teléfono que ya tiene; reloj opcional** |
| IA | Informe mensual con LLM ([2024](https://www.silicon.co.uk/press-release/rune-labs-launches-genai-clinical-support-to-accelerate-care-management-for-parkinsons-patients-and-clinicians)) | Estima puntajes motores | Algoritmos motores | Entiende relatos de varias voces, explica desvíos antes de preguntar, redacta la pregunta y el informe |
| Familia | Lee el resumen | No lo describe | No | **Voz propia con permiso, canal reservado, logros compartidos** |
| Lo no motor que se calla | Notas libres | No lo describe | No | **Pregunta con motivo, a la persona correcta, el mismo día** |
| Dónde | EE. UU. (Kaiser) | Reino Unido (diez organizaciones del NHS) y EE. UU. (Cedars-Sinai, inversor y sitio de piloto) | Europa, Australia, EE. UU. | **Rioplatense, Uruguay y región** |

Cómo les va: Rune Labs es la que más capital levantó: US$57 millones en total según STAT. Kneu es la de mejor momento: con US$11,2 millones sumó dos autorizaciones de la FDA (primero las pruebas activas de temblor en el celular y en 2026 el monitoreo pasivo con Apple Watch) y entró al NHS ([HIT Consultant](https://hitconsultant.net/2026/09/03/fda-clears-kneu-health-apple-watch-parkinsons-tremor-dyskinesia-monitoring/); [STAT](https://www.statnews.com/2025/10/09/parkinsons-disease-symptom-monitoring-tech-startups/)). PKG tiene el único ensayo controlado, pero terminó vendida a Empatica en 2025. Las tres crecieron vendiendo a sistemas de salud, y ninguna está en América Latina.

**Lo decimos primero:** los informes con IA ya existen (StrivePD) y medir con el teléfono también. Nuestro diferencial es el conjunto: la familia como segunda voz, la pregunta con motivo cuando el dato no cierra y una interfaz pensada para un hombre de 74 con temblor. **Debilidades que admitimos:** sin validación clínica, desvíos de la demo inyectados, y la adherencia es el gran problema del rubro.

**El pedido del cierre:** buscamos un neurólogo y un prestador para un piloto de 8 semanas (sección 7).

## 4. Evidencia: qué afirmamos y qué no

**Afirmamos:**
- La información de casa cambia decisiones del neurólogo. En Estocolmo, con 66 pacientes, el plan cambió en el 31,8% de los casos al ver los datos de PKG y el diálogo mejoró en el 88% ([Sundgren 2021](https://pkghealth.com/wp-content/uploads/2023/11/Sundgren-et-al-2021_Does-PKG-Influence-Treatment-Decisions.pdf)). En EE. UU., en 85 consultas, el PKG mostró bradicinesia que el paciente no había contado en 15, discinesia en 10 y temblor en 5 (Joshi 2019). No se suman, porque una consulta puede tener más de uno. Si eso pasa midiendo solo lo motor, lo no motor tiene más margen.
- Kneu reporta que su panel apoyó cambios de medicación en el 53% de las consultas y acortó la consulta un 20% (datos de la propia empresa, AAN).
- Donde registrar síntomas sí mejoró resultados fue porque disparaba una acción a tiempo: en oncología, con 766 pacientes y alertas a enfermería, la supervivencia mediana pasó de 26 a 31,2 meses ([Basch 2017](https://www.mskcc.org/press-releases/real-time-patient-reported-symptom-monitoring-demonstrates-overall-survival-benefit)). Ese es nuestro mecanismo.

**No afirmamos:**
- Que registrar mejore resultados en Parkinson. Con PKG mejoró la parte motora pero no la calidad de vida, y con la app Parkinson's Tracker no cambiaron los síntomas no motores ([Lakshminarayana 2017](https://archive.lstmed.ac.uk/7345/1/npj_Parkinsons_Dis_3_2_2017.pdf), 64% terminó el protocolo).
- Que el juego de golpeteo mida la enfermedad: es una tendencia propia que ayuda a contextualizar, no un diagnóstico.
- Que superamos a StrivePD.

## 5. Negocio (la rúbrica no lo exige; lo tenemos por si preguntan)

El comprador es el prestador de salud; la familia usa Entrecasa gratis. El argumento de venta es menos emergencias e internaciones evitables y neurólogos que siguen a más pacientes con el mismo tiempo. StrivePD reportó 42% menos visitas a emergencias con Kaiser Permanente, antes y después y sin grupo de control. Cuenta con supuestos: un prestador con 300 pacientes a US$15 por mes son unos US$54.000 por año; el 30% de los ~7.000 a 8.000 pacientes de Uruguay, unos US$400.000 por año. El mismo motor sirve para otras enfermedades crónicas con cuidador (demencia, cuerpos de Lewy, ACV) y para la región. Falta resolver: un neurólogo que empuje dentro del prestador, quién custodia los datos (propuesta: el prestador, con alojamiento local) y la regulación de dispositivo médico si escala.

**Siguientes etapas (no se construyen este fin de semana):** app nativa con lectura automática de Salud y Health Connect para Android, reusando esta misma app; WhatsApp para la familia que vive lejos; integración con relojes que ya detectan caídas ([Apple · detección de caídas](https://support.apple.com/en-is/guide/watch/apd34c409704/watchos)) o con la teleasistencia del Sistema de Cuidados ([Presidencia, 2018](https://www.gub.uy/presidencia/comunicacion/noticias/servicio-teleasistencia-del-sistema-cuidados-dispone-capacidad-para-recibir); hay que confirmar cómo funciona hoy); botonera para la etapa avanzada.

## 6. Preguntas que nos van a hacer

1. **"Si le sacás la IA, ¿qué queda?"** Un diario con formularios que nadie llena. La IA entiende lo que cuentan Juan y Marta con sus palabras, decide si un desvío ya está explicado antes de molestar, redacta la pregunta y arma el informe. La tabla muestra la diferencia contra una búsqueda por palabras.
2. **"¿Qué está simulado?"** Las personas, las caídas de pasos (inyectadas y rotuladas), los relatos de la semana (escritos por nosotros y procesados por el sistema en vivo) y el reloj acelerado. La IA, los pasos del teléfono y todo lo que carguen ustedes es real. Está en el README.
3. **"¿En qué se diferencian de StrivePD?"** Ellos resumen lo que anota el paciente con un reloj. Nosotros escuchamos a la familia con permiso, preguntamos el mismo día y con motivo cuando el dato no cierra, y funcionamos con el teléfono que ya tiene.
4. **"¿Por qué una app y no WhatsApp?"** Porque la interfaz es parte del producto: un botón grande para quien tiembla, la pregunta con el gráfico del porqué, el juego y el "Anoté esto" no entran en un chat. WhatsApp tiene sentido para la familia que vive lejos y lo validamos en el piloto.
5. **"¿Y en Android?"** La app es web: funciona igual en Android, y ahí las notificaciones andan incluso sin instalarla. La hicimos en iPhone porque es lo que tenemos los tres. La lectura automática de pasos en Android va con Health Connect en la versión nativa.
6. **"¿No es vigilancia familiar?"** Juan decide quién recibe qué, y lo que Marta marca "solo para el equipo médico" no le llega a Juan. Está en la demo.
7. **"¿Y si el modelo inventa?"** Cada cifra del informe la pone el código y cada cita se verifica carácter por carácter; lo que no coincide se borra y se cuenta.
8. **"¿Y si se equivoca con una emergencia?"** Los rojos son reglas en código con tests; la IA puede subir un aviso, nunca bajarlo. Pruébenlo con el QR.
9. **"¿No es un dispositivo médico?"** Ordena, pregunta y avisa; no diagnostica ni indica dosis. Si escala, se tramita.
10. **"¿El benchmark no es chico y armado por ustedes?"** Sí, y lo decimos. Mide exactamente la promesa (relatos de familia en rioplatense, un corpus que no existe en otro lado), lo etiquetaron dos personas por separado y lo comparamos contra una línea base sin IA.
11. **"¿Y si se cae de noche y nadie se entera?"** El celular solo no lo resuelve, y lo decimos. La siguiente etapa es sugerir un reloj con detección de caídas o teleasistencia cuando las caídas se repiten.

## 7. Piloto después de la hackathon (8 semanas, 1 o 2 neurólogos, 8 a 10 familias)

Medimos: respuesta de la familia en la semana 1 contra la semana 8, preguntas marcadas como "valió la pena", retención, síntomas no motores nuevos que se hablaron en la consulta, cambios de plan con el diseño de Sundgren (el neurólogo escribe el plan antes de ver el informe y lo revisa después), y tiempo de lectura del informe. Criterios para abandonar, fijados antes: menos del 50% de respuesta de la familia en la semana 6, cambios de plan en menos del 15% de los casos, o ningún prestador dispuesto a conversar. Con dos de tres, se replantea.
