import { fmtDate, type Section } from "../../lib/api";
import { D2View, D4View } from "../drafts";
import { Badge, Card } from "../ui";
import { ReviewBar } from "./review-bar";

const KIND_LABEL: Record<Section["kind"], string> = {
  agente: "borrador del agente",
  edicion: "editada",
  aprobacion: "aprobada",
  rechazo: "rechazada",
};

export function SectionCard({ ncrId, section }: { ncrId: string; section: Section }) {
  const title = section.discipline === "D2" ? "D2 · Descripción del problema (5W2H)" : "D4 · Causa raíz";
  const kindTone = { agente: "violet", edicion: "blue", aprobacion: "green", rechazo: "red" } as const;
  return (
    <Card
      title={title}
      actions={
        <>
          <Badge tone={kindTone[section.kind]}>{KIND_LABEL[section.kind]}</Badge>
          <span className="text-xs text-muted">
            v{section.version_no} · {section.author ?? "agente"} · {fmtDate(section.created_at)}
          </span>
        </>
      }
    >
      <div className="grid gap-4">
        {section.kind === "rechazo" && (
          <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800 ring-1 ring-red-200">
            Rechazada: {section.feedback}. El ingeniero vuelve a correr el agente y regenera con esta
            retroalimentación.
          </p>
        )}
        {section.content &&
          (section.discipline === "D4" ? (
            <D4View section={section} ncrId={ncrId} />
          ) : section.discipline === "D2" ? (
            <D2View section={section} ncrId={ncrId} />
          ) : (
            <pre className="overflow-x-auto text-xs">{JSON.stringify(section.content, null, 2)}</pre>
          ))}
        <ReviewBar ncrId={ncrId} section={section} />
      </div>
    </Card>
  );
}
