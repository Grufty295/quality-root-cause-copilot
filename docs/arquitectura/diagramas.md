# Diagramas complementarios

Complementan `c4.md` (contexto, contenedores, componentes y secuencia) y `../seguridad/modelo-de-amenazas.md` (flujo de
datos con fronteras de confianza). Cada bloque es Mermaid: GitHub lo dibuja y se puede pegar tal cual en
<https://mermaid.live>.

## 1. Flujo del agente (LangGraph)

```mermaid
flowchart LR
    classDef nodo fill:#85bbf0,stroke:#5d99c6,color:#0b2a45
    classDef fin fill:#8a8a8a,stroke:#5f5f5f,color:#fff

    S((inicio)) --> g["<b>guard_input</b><br/>injection en la NCR"]:::nodo
    g -->|"alto"| F1["fin: corrida detenida<br/>sin llamadas al modelo"]:::fin
    g --> ga["<b>gather</b><br/>tools y recuperación<br/>cuarentena de fragmentos"]:::nodo
    ga --> d2["<b>d2</b><br/>problema, 1 llamada"]:::nodo
    d2 --> d4s["<b>d4_small</b><br/>causas con citas"]:::nodo
    d4s -->|"d4_retry: guardrail descartó causas"| d4l["<b>d4_large</b><br/>reintento, mismo modelo"]:::nodo
    d4s -->|"sin violaciones"| F2["fin: borradores D2 y D4"]:::fin
    d4l --> F2
```

El reintento (`d4_large`) duplica costo y tiempo; con Qwen 3.6 27B escaló 22 de 36 corridas (ADR 0012). Si ayuda a pasar
el caso no está medido todavía.

## 2. Estados de una corrida

```mermaid
stateDiagram-v2
    [*] --> en_curso: POST /analyze toma cupo
    en_curso --> completada: D2 y D4 válidos
    en_curso --> parcial: una sección descartada
    en_curso --> sin_borrador: ambas descartadas o abstención
    en_curso --> fallida: error del modelo o de la base
    en_curso --> abandonada: el proceso murió antes de cerrar
    completada --> [*]
    parcial --> [*]
    sin_borrador --> [*]
    fallida --> [*]
    abandonada --> [*]
```

El cierre ocurre en un `finally`; `abandonada` solo la marca el proceso que arranca después (hoy no hay reaper: pendiente
con el análisis asíncrono).

## 3. Despliegue

```mermaid
flowchart TB
    classDef c fill:#438dd5,stroke:#2e6295,color:#fff
    classDef ext fill:#8a8a8a,stroke:#5f5f5f,color:#fff
    classDef disen fill:#fff,stroke:#d9822b,color:#7a4a10,stroke-dasharray:4 3
    classDef boundary fill:none,stroke:#6b6b6b,stroke-dasharray:6 4,color:#444

    subgraph poc["PoC (lo que corre hoy) · una máquina, Docker Compose"]
        direction TB
        web["web :3000"]:::c --> api["api :8000"]:::c
        api --> db[("db :5432<br/>solo 127.0.0.1")]:::c
        api --> ol["ollama<br/>perfil local, opcional"]:::c
        api -.-> lfp["Langfuse<br/>compose aparte"]:::c
    end
    api -->|"redactado"| or["OpenRouter / DeepInfra<br/>también simula el local"]:::ext

    subgraph prod["Producción objetivo (diseño, ADR 0012; no construido)"]
        direction TB
        app["web + api<br/>réplicas"]:::disen --> pg[("Postgres<br/>administrado")]:::disen
        app -->|"confidencial"| gpu["servidor GPU en planta<br/>vLLM, Qwen 3.6 27B<br/>RTX 5090 ≈ US$8k"]:::disen
        app -->|"interno o público, opcional"| ap2["proveedor API aprobado"]:::disen
        app -.-> lf2["Langfuse en VPC"]:::disen
    end

    class poc,prod boundary
```

Lo punteado en naranja es diseño: el servidor GPU no existe y su throughput no está medido (ADR 0012).

## 4. Observabilidad: qué viaja y qué no

```mermaid
flowchart LR
    classDef c fill:#438dd5,stroke:#2e6295,color:#fff
    classDef ext fill:#8a8a8a,stroke:#5f5f5f,color:#fff
    classDef no fill:#fff,stroke:#c0392b,color:#c0392b,stroke-dasharray:4 3

    gr["Grafo y gateway<br/>(observador Langfuse)"]:::c
    gr -->|"spans por nodo y llamada<br/>OTLP, TRACE_EXPORTER=langfuse"| lf["Langfuse 3.162<br/>trazas y metadatos"]:::ext
    gr -->|"5 scores numéricos<br/>POST /api/public/scores, 1 objeto por score"| lf
    gr -->|"audit_log: ids, nivel, destino,<br/>tokens, costo, latencia"| db[("Postgres")]:::c
    gr -.-x|"texto de NCR, prompts, salidas"| nada["no sale"]:::no
```

Scores: `escalo_a_modelo_grande`, `violaciones_guardrail`, `errores_llm`, `fragmentos_en_cuarentena`,
`disciplinas_bloqueadas`. Se envían por HTTP propio porque el SDK 5 manda un arreglo que el servidor 3.162 rechaza con 400
(`docs/operacion/observabilidad.md`).

## 5. CI en tres capas

```mermaid
flowchart LR
    classDef gate fill:#438dd5,stroke:#2e6295,color:#fff
    classDef man fill:#fff,stroke:#d9822b,color:#7a4a10,stroke-dasharray:4 3

    pr(["Pull request"]) --> c1["<b>Capa 1 · prompt</b><br/>inyección, PII, PER y ADV<br/>LLM falso"]:::gate
    pr --> c2["<b>Capa 2 · modelo</b><br/>gates sobre el reporte congelado<br/>en evals/reportes/"]:::gate
    pr --> c3["<b>Capa 3 · integración</b><br/>suite completa, Postgres + pgvector<br/>migraciones, audit_verify"]:::gate
    pr --> x["gitleaks (bloquea)<br/>pip-audit (avisa)<br/>tipos y lint del web"]:::gate
    c1 & c2 & c3 & x --> m{{"merge"}}
    man["evals-live.yml<br/>manual, ≈ US$0.15<br/>modelo real, 3 casos"]:::man -.->|"produce el reporte que se congela"| c2
```

La capa 2 evalúa un reporte, no el modelo: cambiar modelo o prompt exige volver a correr el eval y congelar el reporte en
el mismo PR.

## 6. Topología de la prueba de carga

```mermaid
flowchart LR
    classDef c fill:#438dd5,stroke:#2e6295,color:#fff
    classDef t fill:#85bbf0,stroke:#5d99c6,color:#0b2a45

    loc["locust<br/>Analista (POST /analyze)<br/>Lector (GET)"]:::t -->|"HTTP"| api["api<br/>limitador apagado por defecto"]:::c
    api --> db[("db")]:::c
    api -->|"LLM_*__BASE_URL"| stub["stub-llm :9000<br/>latencia fija, max_in_flight"]:::c
    samp["pool_sampler<br/>conexiones del pool cada 2 s"]:::t -.-> api
```

El stub quita al proveedor de la medición: mide la API, el pool y la base, no ningún modelo. Salidas en `traces/carga/`.
