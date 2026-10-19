# ADR 0012 — Inferencia local: costo, capacidad y modelo candidato

**Estado:** Propuesta (calidad en dev: pasa el criterio; falta medir throughput en hardware propio)

## Contexto
En producción, lo confidencial va a un modelo local (ADR 0002). En el dataset el 58 % de las NCR (46 de 80) ya son
confidenciales, y el nivel de una corrida es el máximo de su contexto, así que la fracción real que va a local es
mayor (`SELECT detected_level, destination, count(*) FROM audit_log GROUP BY 1, 2`). La mayor parte de la carga cae en
hardware propio, no en la API.

Hasta ahora la calidad (`dev-v6`, pass@1 0.72) se midió con `deepseek/deepseek-v4.1-flash` por OpenRouter. **Ese número
no describe la ruta confidencial**: ese modelo no es el que correría en una GPU de planta. El "local simulado" no era
solo una salvedad de confidencialidad, también de validez del eval.

Escenario de volumen: `docs/producto/restricciones-y-alcance.md` (0.44 NCR/día en el dataset; ×10 como escala).

## Decisión propuesta
1. **El costo local es un costo fijo de cumplimiento, no algo que se optimice por token.** Se reporta como costo
   imputado por corrida (fijo mensual ÷ corridas) junto con utilización y cola. El costo por token se sigue reportando
   solo para la ruta API.
2. **Modelo candidato: `qwen/qwen3.6-27b`** (denso, 27B, Apache 2.0). Su calidad se mide en OpenRouter con los mismos
   pesos en FP8 (DeepInfra fijo, sin fallback de proveedor). Eso mide calidad, no velocidad en el hardware de planta.
3. **SLO de latencia de la ruta local: p95 ≤ 20 min, con estado visible.** El 8D es trabajo de horas; un SLO de
   segundos obligaría a comprar hardware que la demanda no justifica.
4. **La palanca de capacidad son los tokens de salida**, en particular el razonamiento (63 % con DeepSeek). En la API
   recortarlos ahorra centavos; en local ahorra minutos.

### Criterio de aceptación del candidato (fijado antes de correr)
| Resultado en dev (36 corridas, `con_enlaces`) | Conclusión |
|---|---|
| ≥ 26/36 y gates de tolerancia cero en verde | Equivalente a DeepSeek dentro del ruido; el router puede mandar todo a local |
| > 21/36 (línea base trivial) y < 26 | Viable con pérdida; la pérdida es parte del costo de la confidencialidad |
| ≤ 21/36 o falla un gate de tolerancia cero | No sirve como local con estos prompts |

Sesgo declarado: los prompts se ajustaron sobre dev con DeepSeek. Si Qwen sale peor, parte puede ser ese ajuste. No se
re-itera dev para ajustar prompts a Qwen.

## Requisito contractual de diseño

**Decisión: el sistema se diseña para el caso estricto** (la información del OEM no sale de la planta). Es un supuesto de
diseño: el acuerdo real con el cliente no se ha consultado y debe confirmarse con quien firma ese acuerdo.

- Consecuencia: lo confidencial corre en hardware propio, con el costo fijo de la tabla de abajo.
- **Caso relajado, documentado y no construido:** si el acuerdo admite un proveedor aprobado con contrato de datos, rentar
  una GPU por demanda cuesta entre 15 y 70 veces menos por corrida que comprar (US$0.30 contra US$21 a 13 corridas/mes; US$0.12 contra US$1.9 a 150). El cambio no requiere otra
  arquitectura: el destino "local" es una URL (`LLM_LOCAL__BASE_URL`). Lo que cambia es la garantía, que deja de ser "dentro
  de la planta" y pasa a "con un tercero aprobado", y con ella la redacción del modelo de amenazas (TB3) y el campo
  `simulated`/`provider` de la auditoría.
- Qué faltaría para adoptarlo: el contrato de datos con el proveedor, retención cero verificada y una GPU con su propio
  aislamiento. Nada de eso existe hoy.

## Costo (supuestos en la última sección)

| Opción | 13 corridas/mes (dataset) | 150 corridas/mes (×10) |
|---|---|---|
| Comprar servidor con una RTX 5090 (~US$10k, 36 meses ≈ US$278/mes) | ~US$21 por corrida | ~US$1.9 |
| Rentar GPU bajo demanda (~US$0.85/h, 15 min de arranque por sesión) | ~US$0.30 | ~US$0.12 |
| Rentar GPU 24/7 | ~US$620/mes, peor que comprar | igual |
| API (DeepSeek, `dev-v6`) | US$0.007 | US$0.007 |
| API (Qwen 3.6 27B, DeepInfra 0.32/3.20) | US$0.046 medido en dev (n=36) | igual |

La renta bajo demanda solo existe si el contrato con el OEM admite un **proveedor aprobado**. Con el requisito estricto
(decisión de arriba), la única opción es comprar.

La electricidad no domina: un servidor 24/7 consume del orden de 100 kWh/mes. Con la tarifa GDMTH de Chihuahua
(1.0–1.9 MXN/kWh según el horario, junio de 2026, publicada por un agregador de datos de CFE) son unos US$5–10 de energía
al mes, más el cargo por capacidad si el servidor sube la demanda máxima de la planta. Verificar con el recibo de CFE.

### Punto de equilibrio y valor que no se cuenta

Contando solo horas de ingeniería: sueldo promedio de un ingeniero de calidad en Ciudad Juárez 19,795 MXN/mes (Indeed
México, sept 2026, sueldos autodeclarados; rango 13,399–29,243), con un factor de cargas de 1.4 y 208 h/mes (supuestos)
y 18.42 MXN/USD (FIX, 9 oct 2026): ≈ US$7.2 por hora (rango 4.7–11.5). El servidor (US$278/mes) se paga con ≈ 38 horas
ahorradas al mes (rango 24–59): ≈ 3 h por 8D a 13 corridas/mes, ≈ 15 min a 150.

Ese cálculo es el piso. El valor mayor de llegar antes a la causa raíz está en contener menos días (inspección al
100 %, selección y material en cuarentena), en menos scrap y retrabajo, y en menos riesgo con el cliente (escapes,
cargos por calidad, scorecard):

    valor mensual = días de contención ahorrados × costo diario de contención
                  + reincidencias evitadas × costo por incidente
                  + horas de ingeniería ahorradas × costo por hora

Solo el último término tiene dato. Los otros no se suman sin medirlos: en el piloto en sombra se estiman como la
diferencia entre el día en que el borrador del agente ya señalaba la causa correcta y el día en que el equipo la aprobó,
multiplicada por el costo diario de contención que reporte la planta. La contención (D3) ocurre de todos modos en las
primeras 24 h; lo que el agente puede acortar es cuánto tiempo sigue activa.

## Capacidad (sensibilidad, sin medir en hardware propio)

Humo de Qwen 3.6 27B, 3 corridas, `con_enlaces` (18 oct 2026): por llamada a D4, 14–15k tokens de entrada y 6.5–7.1k de
salida (59 % razonamiento); `finish_reason=stop` en las 4 llamadas; una corrida escaló al modelo grande (mismo modelo) y
duplicó costo y tiempo. Tiempo de modelo ≈ 98–100 s por llamada, es decir ≈ 70 tok/s **en el proveedor** (GPU de centro
de datos); no es una medida del hardware de planta.

Tiempo por llamada de ~7,000 tokens de salida según el throughput que logre la GPU de planta:

| Throughput por flujo | Una llamada | Corrida con escalamiento (2 llamadas) | Ráfaga de 5 sin batching (1 llamada c/u) |
|---|---|---|---|
| 10 tok/s | 12 min | 23 min | 58 min |
| 20 tok/s | 6 min | 12 min | 29 min |
| 30 tok/s | 4 min | 8 min | 19 min |
| 60 tok/s | 2 min | 4 min | 10 min |

Con 20 tok/s o más, una corrida sola (incluso con escalamiento) cabe en el SLO de 20 min. La ráfaga de 5 solo con
batching o con 30 tok/s por flujo. Referencia, no dato: OpenRouter reporta 38–44 tok/s para este modelo.

Mediciones publicadas en una RTX 5090 (sept–oct 2026; no son de nuestra carga): Tom's Hardware midió Qwen 3.8 27B con
vLLM a 20 tok/s sin MTP y 100–110 tok/s con MTP; benchmarks comunitarios reportan 58–80 tok/s para modelos densos de
este tamaño (SpecPicks: 80 tok/s con Qwen 3.6 27B y vLLM 0.19) y ~205 tok/s agregados con 8 flujos simultáneos. Con 20–110
tok/s, una llamada de ~7,000 tokens tarda 1–6 min y una corrida con escalamiento hasta 12 min: cabe en el SLO de 20 min
incluso en el peor caso publicado. La ráfaga de 5 sigue necesitando batching.

Margen de `max_tokens`: las llamadas usaron 6,552–7,082 de 8,192 tokens de salida (hasta 86 %). Una corrida que
razone más se trunca; en dev hay que revisar `finish_reason=length`.

**Límite de memoria de la ráfaga.** Denso 27B en FP8 ≈ 27 GB: en 32 GB quedan ~5 GB de caché KV, insuficiente para 5
contextos de ~32k tokens simultáneos. La ráfaga exige cuantizar a 4 bits (~15 GB), con pérdida de calidad que el eval
en FP8 no mide. Verificar si la arquitectura usa atención híbrida, que reduce la caché.

## Consecuencias
- (+) El costo de la confidencialidad queda explícito y comparable con relajarla.
- (+) Si Qwen es equivalente, todo puede ir a local: sin dependencia de internet, que en planta puede estar restringido.
  El router se conserva como control que falla cerrado; cambia el destino, no la garantía.
- (−) La calidad medida en FP8 sobreestima la de un local en 4 bits.
- (−) Sin GPU propia, el throughput es sensibilidad, no medición. Medirlo cuesta ~€1–2 rentando una 5090 una hora.

## Supuestos
- Precio del servidor: ~US$10k. Equipos completos con RTX 5090 y 128 GB se publicaban en octubre de 2026 entre
  US$9,220 (Best Buy) y US$11,650 (Amazon); integradores desde US$10,000 y hasta ~US$15,000 con más garantía. La tarjeta
  sola: 84,249–149,919 MXN en Cyberpuerta (18 oct 2026), reventa US$4.8–6.3k, lista US$1,999. (Versiones anteriores de
  este ADR usaban ~US$8k.)
- Costo por hora del ingeniero: sueldo de Indeed (autodeclarado); el factor de cargas de 1.4 y las 208 h/mes son
  supuestos, no datos de nómina.
- No incluye el tiempo de TI para operar el servidor; probablemente el costo mayor de comprar, sin base para estimarlo.
- Los tokens y el costo de Qwen salen de `dev-qwen27` (36 corridas, 63 llamadas). El humo (3 corridas) subestimó el costo.

## Evidencia
`make llm-diagnose` con Qwen (18 oct 2026): configuración efectiva, DeepInfra FP8, JSON y `max_tokens=8192` aceptados.
Humo `humo-qwen27` (3 casos, 3/3 pasan, US$0.0357 por corrida): sin fallos de esquema ni truncamiento. 3 de 3 no
distingue 0.72 de 0.9 (intervalo de 95 % ≈ 0.44–1.0): es una prueba de humo, no un resultado de calidad.

### Dev completo `dev-qwen27` (19 oct 2026; 36 corridas, `con_enlaces`, 12 casos × 3, concurrencia 3)
| Medida | Resultado |
|---|---|
| pass@1 | **0.78 (28/36)**; DeepSeek `dev-v6`: 0.72 (26/36). Pasa el criterio (≥ 26/36) |
| Gates de tolerancia cero | salida insegura 0, bloqueadas 0, fallos de esquema 0, inválidas 0 |
| Costo por corrida | US$0.0462 promedio (rango ≈ 0.025–0.084); el humo daba 0.0357 |
| Latencia por corrida | p50 209 s, p95 378 s, máximo 461 s (DeepSeek: p50 85 s) |
| Tokens de salida por corrida | 11,881, de los cuales 59 % razonamiento |
| Llamadas por corrida | 1.8; 22 de 36 escalaron a `d4_large` (mismo modelo) |

**Lectura.**
- *Equivalente, no mejor.* 28 contra 26 son dos corridas. La unidad real son los casos: 9 de 12 pasan 3/3 en ambos.
- *Los fallos son de caso, no de modelo.* EV-07 (1/3), EV-08 (0/3) y EV-10 (0/3) concentran las 8 fallas. En
  `dev-fix` DeepSeek también falla EV-07/08/10 (0/9 cada uno). Ese reporte usa otro `dataset sha` (652d425afc85 contra
  59ed866f944e), así que es indicio y no comparación. Las causas de cada uno son distintas:
  - EV-08 está etiquetado `evidencia_suficiente: false`: lo correcto es abstenerse (`evidencia_insuficiente`) y el modelo
    nunca lo hace (0/3 aquí, 0/9 con DeepSeek en `dev-fix`). Acierta RC-02 y, en 2 de 3, ND-02, pero `pass` exige abstenerse.
    Es el único caso de dev con esa etiqueta: la abstención correcta se mide con n = 1 caso y no basta para concluir nada
    sobre el modelo, aunque sí es un límite que hay que declarar (el agente propone causas donde debería decir "no hay
    evidencia suficiente").
  - EV-10 pone RC-02 sobre la RC-03 esperada en las tres corridas.
  - EV-07 es inestable: la causa esperada queda en el lugar 3, 1 y 2.
- *El escalamiento no se justifica con estos datos.* Las 14 corridas sin escalar pasan 14/14; las 22 escaladas, 14/22.
  Es de esperar (escalan las difíciles) y este reporte no dice si el reintento cambió el resultado, solo cuánto costó:
  una llamada ≈ US$0.026, dos ≈ US$0.052, tres ≈ US$0.080. Falta una corrida con el escalamiento apagado.
- *Truncamiento.* 3 llamadas se cortaron por `max_tokens=8192` (EV-01 r1, EV-07 r2, EV-10 r2) y se reintentaron dentro
  de la misma llamada, con 13–15k tokens de salida y ~200–460 s. Con 59 % de razonamiento el tope queda justo.
  DeepSeek corrió con `reasoning.effort=low`; Qwen no. La comparación de calidad no es de igual configuración.
- *Arranque en frío del embedder confirmado.* La etapa `gather` tardó 38.3, 38.4 y 38.4 s en las tres primeras corridas
  y una mediana de 0.4 s en las demás. Es la hipótesis H2 de `prueba-de-carga.md`.
- *El SLO de latencia por API no se cumple con Qwen* (p95 378 s contra ≤ 180 s del runbook). El de local (≤ 20 min)
  cabe en el escenario medido, pero sin medir en hardware propio.

Pendiente: throughput en hardware propio; corrida con escalamiento apagado; decidir `reasoning.effort` y `max_tokens`
para Qwen (cualquier cambio de configuración exige repetir dev con ambos modelos antes de congelar).
