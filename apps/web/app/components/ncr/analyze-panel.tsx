import { useState } from "react";
import type { Section } from "../../lib/api";
import type { AgentRun } from "../../lib/use-agent-run";
import { Badge, Button, Card, ErrorBox, Spinner, statusTone } from "../ui";

export function AnalyzePanel({ sections, agent }: { sections: Section[]; agent: AgentRun }) {
  const [instructions, setInstructions] = useState("");
  const { running, elapsedMs, last, error } = agent;
  const generable = sections.length < 2 || sections.some((s) => s.kind === "rechazo");
  const mmss = `${Math.floor(elapsedMs / 60000)}:${String(Math.floor((elapsedMs % 60000) / 1000)).padStart(2, "0")}`;

  return (
    <Card
      title="Agente de calidad"
      actions={
        <Button variant="primary" onClick={() => agent.start(instructions)} disabled={running || !generable}>
          {running && <Spinner />} {running ? `Analizando… ${mmss}` : "Correr análisis D2 + D4"}
        </Button>
      }
    >
      <div className="grid gap-3 text-sm">
        {!running && !generable && (
          <p className="text-muted">
            Ya hay borradores sin revisar. El agente solo regenera una sección si no tiene borrador o si fue rechazada.
          </p>
        )}
        {!running && generable && (
          <div className="grid gap-2">
            <p className="text-muted">
              Puedes adjuntar indicaciones técnicas o el resumen del feedback gerencial para guiar al agente en esta corrida.
            </p>
            <textarea
              className="w-full rounded-md border border-border bg-surface p-2 text-sm"
              placeholder="Indicaciones para el agente (ej. Enfocarse en el lote de terminales del proveedor X y descartar la línea L2)..."
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              rows={2}
              maxLength={1000}
            />
          </div>
        )}
        {running && (
          <p className="text-muted">
            Corriendo con las indicaciones proporcionadas. Puedes cambiar de pestaña; el resultado aparece aquí al terminar.
          </p>
        )}
        {last && (
          <p>
            Última corrida: <Badge tone={statusTone(last.status)}>{last.status}</Badge>
            {last.duration_ms ? <span className="text-muted"> · {(last.duration_ms / 1000).toFixed(0)} s</span> : null}
            {Object.entries(last.blocked).map(([d, why]) => (
              <span key={d} className="mt-1 block text-xs text-red-700">
                {d} bloqueado: {why}
              </span>
            ))}
          </p>
        )}
        <ErrorBox error={error} />
      </div>
    </Card>
  );
}
