# Defensa de decisiones

Para quien evalúe el proyecto, sea técnico o no. Dice qué problema resuelve, qué decisiones lo definen, qué se sacrificó en cada una y qué falta demostrar. El detalle de ingeniería está en los [ADR](adr/README.md); aquí solo lo que sostiene el argumento.

## El problema y la propuesta

Cuando una planta de manufactura recibe un reporte de no conformidad, encontrar la causa raíz y documentarla (el informe 8D) toma horas, y el conocimiento de casos anteriores está disperso en documentos. Usar una IA pública para acelerarlo expone información que los clientes exigen que no salga de la planta.

**La propuesta:** un asistente que lee el reporte, busca casos y datos anteriores y redacta un borrador de las secciones de análisis (D2 y D4) con causas posibles y las fuentes en que se apoya. **Un ingeniero revisa y un gerente aprueba. El asistente nunca cierra un caso.** Lo confidencial se procesa con un modelo propio, no con una API externa.

## Lo que se logró

- **Funciona de punta a punta:** reporte de entrada, borrador con fuentes, revisión, aprobación y un registro de auditoría que no se puede alterar sin que se note.
- **Encuentra la causa correcta:** en las pruebas, la causa real estuvo entre las tres primeras propuestas en todas las corridas, y en primer lugar en cerca de 7 de cada 10 (26 de 36).
- **El modelo que correría en la planta rinde igual:** el candidato de pesos abiertos (Qwen 3.6 27B) acertó 28 de 36 en las mismas pruebas. Es un empate dentro del ruido, no una mejora, pero responde la pregunta de si la confidencialidad cuesta calidad: con estos datos, no.
- **El costo está en el servidor, no en la IA:** por API, un análisis cuesta menos de un centavo de dólar con DeepSeek y unos 5 centavos con el modelo candidato. Lo confidencial necesita un servidor propio de ~US$10k (≈ US$278 al mes a tres años).
- **Está probado y automatizado:** más de 750 pruebas automáticas, y una verificación continua en GitHub que revisa seguridad, calidad y secretos filtrados en cada cambio.

## Las decisiones que lo definen

**1. La persona decide; la IA propone.**
*Qué se sacrificó:* velocidad total. Cada borrador pasa por un ingeniero y por un gerente que no puede ser quien lo redactó.
*Por qué vale la pena:* en calidad automotriz alguien tiene que responder por la causa. Un sistema que cierra casos solo no sería aceptado, y con razón.

**2. Lo confidencial no sale de la planta, y eso se impone en tres capas.**
Un "router" decide a dónde va cada consulta según su nivel de confidencialidad; los datos se anonimizan antes de enviarse; y la base de datos rechaza la combinación prohibida aunque el código fallara.
*Qué se sacrificó:* simplicidad y costo. Hace falta correr un modelo propio, que es más caro que pagar una API: con el volumen del caso, el servidor sale en unos US$21 por análisis, contra menos de 5 centavos por API.
*Por qué vale la pena:* es la razón de existir del proyecto. Sin esto no se podría usar con datos reales de clientes.

**3. Respuestas verificables, no texto libre.**
El asistente solo puede proponer causas de un catálogo de la planta y debe citar la fuente de cada una; un control automático descarta las que no cumplan. No muestra "porcentajes de confianza".
*Qué se sacrificó:* no puede descubrir una causa que no esté en el catálogo.
*Por qué vale la pena:* cada propuesta se puede comprobar. Un porcentaje inventado por una IA daría una falsa sensación de precisión.

**4. Reglas simples donde alcanzan; IA solo donde hace falta.**
Los permisos, el catálogo cerrado, las citas y la auditoría son reglas y código normal. El modelo solo redacta.
*Qué se sacrificó:* flexibilidad.
*Por qué vale la pena:* es más fácil de probar, de auditar y de explicar a quien no es técnico.

**5. Medir con honestidad, aunque el número se vea peor.**
Hay una parte de los casos de prueba reservada y sin tocar, la evaluación no usa otra IA como juez, y cada cifra viene con su límite.
*Qué se sacrificó:* un titular más vistoso.
*Por qué vale la pena:* un número inflado se cae en cuanto alguien lo prueba con datos reales.

**6. Alcance de prototipo, declarado.**
Corre en una sola máquina con datos ficticios. Los secretos, el despliegue y la escala son de prototipo, y cada recorte está escrito.
*Por qué vale la pena:* es más útil entregar algo pequeño y comprobado que algo grande y sin verificar.

## Lo que todavía no está demostrado

- **No se ha probado con datos reales.** Los datos son ficticios y los generé yo, con el mismo catálogo que usa el asistente. Eso favorece los resultados.
- **Las pruebas son pocas.** Con 12 casos de ajuste y otros 8 reservados, los 7 de cada 10 son un indicio, no una precisión garantizada. Una regla simple (copiar la causa del caso más parecido) acierta 7 de 12. El asistente le gana, por poco y con pocos datos.
- **El modelo "propio" todavía no corre en la planta.** Su calidad ya se midió, pero a través de un servicio externo y sin la compresión que necesitaría en una sola GPU. Se demuestra que el mecanismo de protección funciona y que el modelo candidato rinde; la garantía de que nada sale de la planta, y su velocidad real, requieren instalarlo en el servidor de la planta.
- **No sabe decir "no hay evidencia suficiente".** En el único caso de prueba donde lo correcto era abstenerse, siempre propuso causas. El revisor humano lo cubre, pero es un límite de comportamiento que hay que corregir.
- **El ahorro no está medido.** Las horas de ingeniería, los días de contención, el scrap y los reclamos que se evitarían dependen de datos reales de la planta. El piloto existe para medirlos.
- **La defensa contra instrucciones maliciosas escondidas en los textos es parcial.** Detecta una parte de los intentos. El diseño asume que a veces falla, y por eso el asistente solo puede leer, no puede ejecutar acciones, y un humano revisa todo.
- **Una prueba de carga encontró un fallo real,** que se corrigió, pero no se repitió la prueba completa después de la corrección.

## Qué sigue

1. **Probar con los casos reservados,** una sola vez y con la configuración final, para saber si los resultados se sostienen.
2. **Probarlo con casos reales y un ingeniero de calidad** que juzgue las propuestas, y medir cuántos días antes habría llegado a la causa y cuánto cuesta cada día de contención.
3. **Instalar el modelo en la planta,** para cumplir de verdad la promesa de confidencialidad.
4. **Medir cómo se comporta ante textos maliciosos** con el modelo real, no solo con uno simulado.

## Preguntas que podrían hacerme

**¿Por qué creerle a un 72 %?**
No como una cifra de precisión. Muestra que el asistente funciona y supera una regla simple, y que casi siempre pone la causa correcta entre las primeras tres. El modelo que correría en planta dio 28 de 36 (78 %), que es lo mismo dentro del ruido. Para afirmar más hacen falta más casos y datos reales.

**¿Vale lo que cuesta el servidor?**
Contando solo horas de ingeniería (un ingeniero de calidad en Juárez cuesta unos US$7 por hora con cargas, estimado), el servidor se paga con unas 38 horas ahorradas al mes: unas 3 horas por 8D con el volumen del caso, o 15 minutos si el volumen fuera diez veces mayor. Ese es el piso. El valor mayor está en contener menos días, generar menos scrap y reducir el riesgo con el cliente, y eso no lo sumo sin medirlo. Además, sin el servidor la opción no es "IA más barata": es no usar IA con datos del cliente.

**¿Qué pasa si la IA se equivoca?**
Está previsto: propone, no decide. Cada propuesta cita sus fuentes, un ingeniero la revisa y un gerente la aprueba. El peor caso es una causa sugerida que el revisor rechaza.

**¿Cómo sé que mis datos confidenciales no salen?**
El sistema decide a dónde enviar cada consulta, lo registra y lo impone en la base de datos. En este prototipo el modelo propio es una simulación; con datos reales habría que instalarlo en la planta. Está dicho en el PRD y en la auditoría.

**¿Por qué no usar directamente ChatGPT?**
Porque los acuerdos con clientes lo impiden, y porque en calidad se necesita saber de dónde sale cada afirmación y quién la aprobó. Un chat no da ni lo uno ni lo otro.

**Cambiaste algunas etiquetas de prueba después de ver los resultados. ¿Maquillaste algo?**
Cambié dos etiquetas de casos de ajuste después de verlos, y lo declaré. Reporto ambos resultados (29 y 28 de 36), y los casos reservados siguen sin abrir. Esos son los que decidirán.

## Para quien quiera el detalle técnico

- Decisiones de arquitectura: [`docs/adr/`](adr/README.md)
- Seguridad y amenazas: [`docs/seguridad/modelo-de-amenazas.md`](seguridad/modelo-de-amenazas.md)
- Evaluación y métricas: [`docs/evaluacion.md`](evaluacion.md)
- Operación, carga y CI: [`docs/operacion/`](operacion/)