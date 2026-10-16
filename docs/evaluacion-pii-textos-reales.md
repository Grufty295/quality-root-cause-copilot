# Evaluar la detección de PII con textos reales

Por qué: el dataset sintético lo escribió el mismo equipo que escribió las reglas.
Un recall alto ahí es circular: mide si las reglas reconocen lo que su autor imaginó.
Y para PII, un falso negativo es una fuga.

## 1. De dónde salen los textos (en orden de preferencia)

1. **Históricos de la propia planta**: NCR, 8D, órdenes de mantenimiento, bitácoras. Es la única
   fuente con el vocabulario, las abreviaturas y los errores reales. Requiere autorización escrita
   de calidad y del responsable de datos personales; hay empleados identificables (LFPDPPP).
   Se trabaja dentro del entorno de la empresa; solo salen métricas.
2. **Texto elicitado a expertos**: pedir a 2-3 ingenieros de calidad que escriban 30-50 descripciones
   "como las escribirían un martes a las 6 am" a partir de casos que recuerden, con nombres
   inventados pero con sus costumbres de escritura. No es real, pero sí es de otra mano.
3. **Corpus públicos para el eje de nombres y PII general** (dominio distinto: miden NER en español,
   no tu jerga): CoNLL-2002 español, MEDDOCAN (anonimización de texto clínico en español),
   conjuntos sintéticos multilingües de PII. Verificar licencia y que incluyan español antes de usarlos.

No hay un corpus público de NCR de manufactura en español de México. Si alguien dice lo contrario,
revisar que no sea sintético.

## 2. Qué buscar al muestrear

Estratificar por línea, turno, familia de defecto, autor y longitud; incluir deliberadamente casos difíciles:

* abreviaturas y roles recortados: "Op.", "Sup.", "Ing. Hdz";
* nombres solos, apodos, solo iniciales, TODO EN MAYÚSCULAS, sin acentos;
* alias del cliente ("NR") y partes truncadas ("4471B");
* texto tipo WhatsApp, errores de captura, mezcla inglés-español;
* referencias indirectas ("el de la bata azul del turno 2") que ninguna regla va a atrapar.

## 3. Cómo etiquetar

* Dos personas, por separado, marcando **spans** con tipo: persona, nómina, correo, teléfono, cliente, parte, otro identificador.
* Guía escrita con casos límite; medir acuerdo entre anotadores (kappa o F1 entre ellos). Si discrepan mucho, la guía está mal, no el sistema.
* **Separar un conjunto de prueba que nadie mire al ajustar reglas.** Lo que se usa para afinar deja de servir para medir.

## 4. Qué medir

* **Recall por span y por documento** ("el documento tiene al menos una fuga"). El de documento es el que importa para la política.
* Precisión (sobre-redacción) como métrica secundaria, y su efecto en la calidad del análisis: comparar el borrador de D4 con y sin redacción.
* Intervalos de confianza. Con 0 fallos en n instancias, la cota superior al 95 % de la tasa de fallo es ~3/n (regla del tres): para
  poder decir "menos de 5 % de fuga" hacen falta unas 60 instancias de PII sin un solo fallo; para 1 %, unas 300.
* Por tipo, no solo global: un buen recall en correos no compensa uno malo en nombres.

## 5. Manejo y fixtures

* Los originales no entran al repositorio ni a ninguna herramienta externa.
* Para pruebas de regresión: **sustitutos**. Reemplazar cada dato real por uno falso con la misma forma
  (mismo rol, mismas mayúsculas, mismo error de captura). Se conserva el contexto lingüístico y se pierde el dato.
* Registrar en el reporte: tamaño, origen, fecha, quién etiquetó, y que el conjunto de prueba es independiente.

## 6. Decisión que habilita

Con este conjunto se compara `RuleRedactor` contra un adaptador de Presidio (con reconocedores `es` y la lista del catálogo)
y contra la combinación de ambos. Se adopta lo que reduzca fugas por documento sin degradar el análisis, no lo que tenga mejor fama.
