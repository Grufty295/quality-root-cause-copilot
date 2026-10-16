# Redactor y seudonimizador (RF-04)

Cierra el circuito del destino `api`: antes de salir, el texto pasa por el redactor;
el inspector verifica el resultado; la respuesta vuelve con los valores reales.

```
mensajes ──► RuleRedactor ──► CatalogInspector ──► cliente api ──► respuesta ──► restore ──► agente
             (reemplaza)      (verifica, bloquea)                    [PERSONA_1] → "Ana Ruiz"
                 │
                 └── pseudonym_map (valores en claro, por NCR, 90 días)
```

## Qué reemplaza

| Tipo | Origen | Marcador |
|---|---|---|
| cliente | catálogo (nivel interno o confidencial; lo público pasa) | `[CLIENTE_n]` |
| parte | catálogo, y códigos con forma de parte que no están en él | `[PARTE_n]` |
| persona | rol + nombre propio; después, cualquier mención del mismo nombre en la NCR | `[PERSONA_n]` |
| nomina | "nómina/empleado/gafete 12345" | `[NOMINA_n]` |
| correo | direcciones de correo | `[CORREO_n]` |

Mismo valor → mismo marcador dentro de una NCR, sin importar mayúsculas, acentos
ni separadores (`ax 4471 b` = `AX-4471-B`). Al restaurar, el valor vuelve en su
forma canónica (la del catálogo o la primera vez que se vio).

## Garantías y límites

* **Falla cerrado.** Si el redactor o el almacén fallan, `RedactionFailed`: no sale
  nada y la llamada queda auditada como `blocked`.
* **No es la última barrera.** El inspector sigue revisando el payload ya redactado.
* **Auditoría sin valores.** `tags.redactions` lleva tipos y conteos (`cliente=1,persona=2`).
* **El gateway con destino api exige redactor** (igual que el inspector).
* **El destino local no se redacta**: lo confidencial se queda en la planta.
* **PII heurística.** Un nombre sin rol delante, la primera vez que aparece en una NCR, no se
  detecta. Tampoco alias de cliente ("NR"), partes truncadas (`4471B`) ni referencias
  indirectas ("el de la bata azul"). Ver `docs/evaluacion-pii-textos-reales.md`.
* **Falsos positivos por diseño.** Igual que el inspector, la búsqueda ignora separadores, así que
  un término corto puede coincidir dentro de una palabra. Se prefiere sobre-redactar a filtrar.
* **Retención.** `expires_at` = 90 días desde el último uso. Todavía no hay proceso que purgue.
* **Catálogo en memoria.** `RuleRedactor` recibe los términos al construirse; si el catálogo
  cambia hay que reconstruirlo (igual que el inspector).

## Cableado

```python
terms = ncr_repo.catalog_terms(conn)                       # clientes y partes con su nivel
store = SqlPseudonymStore(engine.begin)                    # transacción propia, como SqlAuditSink
redactor = RuleRedactor(terms, store)
gateway = ModelGateway(settings, clients, SqlAuditSink(engine.begin), inspector, redactor)
```

`Redactor` es un `Protocol`: un adaptador de Presidio puede ocupar su lugar sin tocar el
gateway. Para decidir si vale la pena, medir ambos con el protocolo de evaluación.
