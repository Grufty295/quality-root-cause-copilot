"use client";

import type { Causa, D2Content, D4Content, FuenteRef, Hecho } from "../lib/api";
import { Badge, levelTone } from "./ui";

function refLabel(ref: FuenteRef | undefined): string {
  if (!ref) return "fuente sin índice";
  if (ref.tipo === "fragmento") return [ref.documento, ref.seccion].filter(Boolean).join(" · ") || "fragmento";
  if (ref.tipo === "herramienta") {
    const p = ref.parametros
      ? Object.entries(ref.parametros)
          .map(([k, v]) => `${k}=${v}`)
          .join(", ")
      : "";
    return `${ref.herramienta ?? "herramienta"}${p ? ` (${p})` : ""}`;
  }
  return "la NCR";
}

export function Sources({ ids, index }: { ids: string[]; index: Record<string, FuenteRef> }) {
  return (
    <span className="ml-1 inline-flex flex-wrap gap-1 align-middle">
      {ids.map((id) => {
        const ref = index[id];
        return (
          <Badge key={id} tone={levelTone(ref?.nivel)} title={`${refLabel(ref)}${ref?.nivel ? ` · ${ref.nivel}` : ""}`}>
            <span className="font-mono">{id}</span>
            <span className="max-w-48 truncate font-normal opacity-80">{refLabel(ref)}</span>
          </Badge>
        );
      })}
    </span>
  );
}

function Facts({ items, index, tone = "plain" }: { items?: Hecho[]; index: Record<string, FuenteRef>; tone?: "plain" | "against" }) {
  if (!items?.length) return null;
  return (
    <ul className="grid gap-1.5">
      {items.map((h, i) => (
        <li key={i} className={`text-sm leading-relaxed ${tone === "against" ? "text-red-800" : ""}`}>
          <span className="mr-1 text-muted">{tone === "against" ? "✕" : "•"}</span>
          {h.texto}
          <Sources ids={h.fuentes} index={index} />
        </li>
      ))}
    </ul>
  );
}

function CauseBlock({ c, rank, index }: { c: Causa; rank: string; index: Record<string, FuenteRef> }) {
  return (
    <article className="grid gap-2 rounded-md border border-border p-3">
      <header className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-muted">{rank}</span>
        <span className="font-mono text-sm font-semibold">{c.codigo}</span>
        {c.respaldo && (
          <Badge
            tone={c.respaldo === "caso" ? "green" : "amber"}
            title={
              c.respaldo === "caso"
                ? "Cita evidencia del caso: datos, NCR, 8D o instrucciones"
                : "Solo cita su fila del catálogo: es una hipótesis por verificar"
            }
          >
            {c.respaldo === "caso" ? "respaldo del caso" : "solo catálogo"}
          </Badge>
        )}
      </header>
      <p className="text-sm leading-relaxed">{c.explicacion}</p>
      <div className="grid gap-1">
        <h4 className="text-xs font-semibold text-muted">Evidencia</h4>
        <Facts items={c.evidencia} index={index} />
      </div>
      {!!c.evidencia_contradictoria?.length && (
        <div className="grid gap-1">
          <h4 className="text-xs font-semibold text-red-700">Evidencia en contra</h4>
          <Facts items={c.evidencia_contradictoria} index={index} tone="against" />
        </div>
      )}
      <dl className="grid gap-1 text-sm sm:grid-cols-[10rem_1fr]">
        <dt className="text-xs font-semibold text-muted">Para confirmarla</dt>
        <dd>{c.pregunta_confirmacion}</dd>
        {c.refutaria && (
          <>
            <dt className="text-xs font-semibold text-muted">La descartaría</dt>
            <dd>{c.refutaria}</dd>
          </>
        )}
        {c.dato_faltante && (
          <>
            <dt className="text-xs font-semibold text-muted">Dato faltante</dt>
            <dd>{c.dato_faltante}</dd>
          </>
        )}
      </dl>
    </article>
  );
}

export function D4View({ content }: { content: D4Content }) {
  const index = content.indice_fuentes ?? {};
  const insufficient = content.estado === "evidencia_insuficiente";
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={insufficient ? "amber" : "green"}>
          {insufficient ? "Evidencia insuficiente: lista de verificación" : "Candidato respaldado"}
        </Badge>
        {content.estado_motivo && <span className="text-xs text-muted">{content.estado_motivo}</span>}
      </div>
      <div className="grid gap-2">
        <h3 className="text-sm font-semibold">Causas de ocurrencia (de más a menos probable)</h3>
        {content.causas_ocurrencia.map((c, i) => (
          <CauseBlock key={c.codigo + i} c={c} rank={`#${i + 1}`} index={index} />
        ))}
        {content.causas_ocurrencia.length === 0 && (
          <p className="text-sm text-muted">El guardrail descartó todas las causas propuestas.</p>
        )}
      </div>
      {content.causa_no_deteccion && (
        <div className="grid gap-2">
          <h3 className="text-sm font-semibold">Causa de no detección</h3>
          <CauseBlock c={content.causa_no_deteccion} rank="ND" index={index} />
        </div>
      )}
      {!!content.descartes?.length && (
        <div className="grid gap-1">
          <h3 className="text-sm font-semibold">Descartadas por el guardrail</h3>
          <ul className="grid gap-1 text-sm">
            {content.descartes.map((d, i) => (
              <li key={i}>
                <span className="font-mono font-medium">{d.codigo}</span>
                <span className="text-muted"> · {d.motivo}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

const D2_FIELDS: [keyof Omit<D2Content, "indice_fuentes">, string][] = [
  ["que", "Qué"],
  ["por_que", "Por qué es un problema"],
  ["donde", "Dónde"],
  ["cuando", "Cuándo"],
  ["quien", "Quién lo detectó"],
  ["como", "Cómo"],
  ["cuanto", "Cuánto"],
];

export function D2View({ content }: { content: D2Content }) {
  const index = content.indice_fuentes ?? {};
  return (
    <dl className="grid gap-x-4 gap-y-2.5 sm:grid-cols-[10rem_1fr]">
      {D2_FIELDS.map(([key, label]) =>
        content[key] ? (
          <div key={key} className="contents">
            <dt className="text-xs font-semibold text-muted">{label}</dt>
            <dd className="text-sm leading-relaxed">
              {content[key].texto}
              <Sources ids={content[key].fuentes} index={index} />
            </dd>
          </div>
        ) : null,
      )}
    </dl>
  );
}
