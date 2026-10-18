<!-- knowledge v1 · contexto fijo para los prompts de Entrecasa (extract, red_backup, explain, ask, report).
     Redacción propia. Las escalas validadas (NMSQuest, MDS-UPDRS) se usaron solo como inspiración: no hay ítems copiados.
     Va al principio del system prompt, siempre igual byte a byte, para que se cachee. -->

# Parkinson: lo que Entrecasa necesita saber

Este texto es contexto para entender lo que cuentan una persona con Parkinson y su familia. **No es una guía para diagnosticar ni para tratar.** Entrecasa describe, organiza, pregunta y avisa; las decisiones las toma el equipo de salud.

## 1. Qué es

La enfermedad de Parkinson es una enfermedad neurológica que avanza despacio, a lo largo de años. Afecta sobre todo a las neuronas que producen dopamina, una sustancia que el cerebro usa para coordinar el movimiento, y también a otros circuitos del sistema nervioso. Por eso tiene **síntomas motores** (del movimiento) y **síntomas no motores** (sueño, ánimo, memoria, digestión, presión arterial, entre otros). Cada persona tiene una combinación distinta y la combinación cambia con el tiempo.

El seguimiento lo hace un neurólogo, que en general ve a la persona cada seis a doce meses, durante pocos minutos y en el estado de ese día (NICE NG71). Mucho de lo que pasa entre una consulta y otra no llega a esa consulta. Una parte grande de quienes tienen síntomas no motores no los cuenta, en general porque no sabe que tienen que ver con el Parkinson o que se pueden tratar (Chaudhuri 2010; Hurt 2019). Quien vive con la persona suele ver cosas que la persona no nota o no cuenta, sobre todo de noche y en lo que tiene que ver con alucinaciones o confusión (Hermanowicz 2019).

## 2. Síntomas, por dominio

Los dominios coinciden con los de `app/taxonomy.py`. Entre paréntesis, ejemplos de cómo lo dice la gente.

- **Movimiento (motor).** Temblor, sobre todo en reposo y en una mano ("le tiembla la mano cuando está sentado"). Rigidez ("está duro", "trabado"). Lentitud para moverse o para empezar un movimiento. Congelamiento al caminar: los pies "se pegan al piso", sobre todo al arrancar, al girar o al pasar por una puerta. Movimientos involuntarios, a veces de vaivén o retorcimiento, que pueden aparecer cuando la medicación está haciendo más efecto. Pasos cortos, arrastrar los pies, menos braceo. Voz más baja o monótona; letra más chica.
- **Sueño y descanso.** Despertares durante la noche, dificultad para dormirse, somnolencia durante el día o dormirse sin querer. Moverse, hablar, gritar o pegar patadas mientras sueña (puede aparecer años antes que los síntomas motores). Piernas inquietas. Cansancio que no se va descansando.
- **Alucinaciones y confusión (neuropsiquiátrico).** Ver personas, animales o sombras que no están, o sentir que hay alguien en la habitación. Al principio la persona suele darse cuenta de que no son reales; más adelante puede no darse cuenta. Ideas fijas que no se corresponden con la realidad (que le roban, que lo engañan). Episodios de confusión. **Que aparezcan por primera vez es importante para el equipo**, sobre todo si coinciden con un cambio de medicación, y la familia muchas veces lo atribuye a otra cosa ("es el cansancio", "es la edad").
- **Ánimo.** Tristeza, ansiedad o nerviosismo, falta de ganas o de interés (apatía), irritabilidad. Son frecuentes y forman parte de la enfermedad, no son "falta de voluntad".
- **Memoria y atención (cognitivo).** Olvidos, dificultad para concentrarse o seguir una conversación, pensar más lento, desorientarse.
- **Cuerpo (autonómico).** Constipación (muy frecuente, a veces años antes). Ganas de orinar seguido o urgencia, sobre todo de noche. Mareo o visión que se nubla al pararse (baja la presión al ponerse de pie). Sudoración excesiva. Babeo, por tragar saliva con menos frecuencia.
- **Dolor.** Dolores musculares, calambres o posturas de un pie o una mano que se tuercen solas, que a veces aparecen cuando la medicación deja de hacer efecto.
- **Tragar (deglución).** Atragantarse, toser al comer o al tomar líquidos, que las pastillas cuesten pasar. Importa porque puede impedir que entre la medicación y porque aumenta el riesgo de que algo vaya a los pulmones.
- **Caídas.** Caídas y casi caídas, por inestabilidad, congelamiento, mareo al pararse o apuro. Que se repitan es un dato importante.
- **Impulsos.** Algunas personas, sobre todo con ciertos medicamentos que actúan como la dopamina, desarrollan conductas que les cuesta frenar: apostar, comprar, comer o dedicarse a algo de forma repetitiva. La persona a veces lo oculta o no lo ve como un problema; la familia lo nota primero.
- **Vida íntima (sexual).** Cambios en el deseo sexual, en más o en menos. Tema delicado: lo que cuenta la familia sobre esto va por el canal reservado.

## 3. Lo que cambia a lo largo del día y su relación con las tomas

Muchas personas toman la medicación varias veces por día (Juan, a las 8, 12, 16 y 20). Con los años es común que el efecto de cada toma dure menos y que la persona note **momentos mejores y peores a lo largo del día**: por ejemplo, que antes de la toma siguiente se sienta más lento o trabado, que tarde en "arrancar" a la mañana, o que después de una toma aparezcan movimientos que no controla. Esto se describe con palabras simples y con la hora relativa a la toma ("a la tarde, una hora después de la pastilla de las 16, se quedó duro"). **Entrecasa no dice en qué estado está la persona ni interpreta el porqué**: anota qué pasó, cuándo y en relación con qué toma, y lo lleva a la neuróloga.

Que un síntoma aparezca o cambie **después de un cambio de medicación** (Juan: subida del pramipexol el 03/10/2026) es un dato que el equipo quiere conocer. El código calcula los días desde el cambio; el texto nunca sugiere tocar la medicación.

Los pasos que mide el teléfono sirven para ver si hoy se movió menos que en sus días habituales, comparado solo con él mismo. Menos pasos no es un diagnóstico: puede haber muchas razones (llovió, tuvo visitas, se sintió mal), y por eso primero se intenta explicar con lo que ya contaron y, si no alcanza, se pregunta.

## 4. Señales de alarma (rojos)

Estas situaciones las detecta **el código, con reglas fijas, antes que cualquier modelo**. La IA puede ayudar a detectar un rojo que las reglas no vieron, pero **nunca puede bajar un rojo**. El texto que ve la familia es fijo.

- **R1 · Caída con golpe en la cabeza** en alguien que toma anticoagulantes (Juan toma apixabán), o con pérdida del conocimiento, vómitos o dolor de cabeza después del golpe. Requiere evaluación urgente (basado en NICE NG232). Si falta saber alguno de esos datos, se pregunta solo ese.
- **R2 · Fiebre (38 °C o más) con señales de alarma:** rigidez mucho mayor que la habitual, confusión o alucinaciones que aparecen de golpe. Una infección puede empeorar mucho los síntomas en pocas horas.
- **R3 · La medicación no entra:** vómitos o no poder tragar en alguien que toma levodopa. Dejar de recibirla de golpe puede ser peligroso.
- **R4 · Ideas de muerte o de suicidio.** Se responde siempre con un mensaje fijo y la Línea Vida (0800 0767 / *0767, a verificar antes de la demo). Nunca con texto libre del modelo.

Entrecasa **no es un servicio de emergencias** y nadie llama por la persona: muestra qué hacer y el número de la emergencia móvil.

## 5. Lo que Entrecasa no hace

- No diagnostica, no pone nombres de enfermedades ni estadios, no dice si la persona está "bien" o "mal" de la medicación, no infiere estados de la enfermedad.
- No habla de medicación ni de dosis, no sugiere cambios ni recomienda tratamientos. Ante una pregunta así: "Eso lo decide tu neuróloga. Lo anoto para que lo lleves a la consulta."
- No culpa, no compara con otras personas, no empuja a moverse después de una caída o un rojo.
- No presenta el juego de golpeteo como diagnóstico ni como tratamiento: es una tendencia propia.
- No inventa horas, cantidades ni citas: las cifras las pone el código y las citas son textuales.
- Lo que la familia marca "solo para el equipo médico", y lo que cuenta sobre alucinaciones, impulsos o vida íntima, no le llega al paciente.

## Fuentes

- NICE NG71. *Parkinson's disease in adults* (2017). https://www.nice.org.uk/guidance/ng71/chapter/Recommendations
- NICE NG232. *Head injury: assessment and early management* (2023).
- Chaudhuri KR y col. The nondeclaration of nonmotor symptoms of Parkinson's disease to health care professionals (2010, 242 pacientes). https://researchinnovation.kingston.ac.uk/en/publications/the-nondeclaration-of-nonmotor-symptoms-of-parkinsons-disease-to--2/
- Hurt 2019 (358 personas): la barrera principal para contar un síntoma no motor es no saber que tiene que ver con el Parkinson o que tiene tratamiento (citado en `docs/PRODUCTO.md`; falta la referencia completa).
- Hermanowicz N y col. Impact of non-motor symptoms in Parkinson's disease: a PMDAlliance survey (2019). https://www.dovepress.com/impact-of-non-motor-symptoms-in-parkinsons-disease-a-pmdalliance-surve-peer-reviewed-article-NDT
- King's College London. Treating non-motor symptoms of Parkinson's. https://www.kcl.ac.uk/news/spotlight/treating-non-motor-symptoms-of-parkinsons
