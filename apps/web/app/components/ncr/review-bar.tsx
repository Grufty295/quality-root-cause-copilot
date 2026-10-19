import { useState } from "react";
import { errorText, REJECT_REASONS, type Section } from "../../lib/api";
import { useApproveSection, useEditSection, useRejectSection } from "../../lib/queries";
import { Button, ErrorBox, Spinner } from "../ui";
import { useUser } from "../shell";

export function ReviewBar({ ncrId, section }: { ncrId: string; section: Section }) {
  const user = useUser();
  const approve = useApproveSection(ncrId);
  const reject = useRejectSection(ncrId);
  const edit = useEditSection(ncrId);
  const [mode, setMode] = useState<"none" | "reject" | "edit">("none");
  const [feedback, setFeedback] = useState("");
  const [reason, setReason] = useState("");
  const [json, setJson] = useState("");
  const [jsonError, setJsonError] = useState<string | null>(null);

  const final = section.kind === "aprobacion";
  const canEdit = user.role === "ingeniero" && !final && section.content !== null;
  const canReject = (user.role === "ingeniero" || user.role === "gerente") && !final && section.kind !== "rechazo";
  const canApprove = user.role === "gerente" && !final && section.kind !== "rechazo" && section.content !== null;
  if (!canEdit && !canReject && !canApprove) return null;

  const busy = approve.isPending || reject.isPending || edit.isPending;
  const error = jsonError ?? errorText(approve.error ?? reject.error ?? edit.error);
  const target = { discipline: section.discipline, version: section.version_no };
  const done = {
    onSuccess: () => {
      setMode("none");
      setFeedback("");
      setReason("");
    },
  };

  function saveEdit() {
    let content: unknown;
    try {
      content = JSON.parse(json);
    } catch {
      setJsonError("El JSON no es válido");
      return;
    }
    setJsonError(null);
    edit.mutate({ ...target, content }, done);
  }

  return (
    <div className="grid gap-3 border-t border-border pt-3">
      <div className="flex flex-wrap gap-2">
        {canApprove && (
          <Button variant="primary" disabled={busy} onClick={() => approve.mutate(target)}>
            Aprobar v{section.version_no}
          </Button>
        )}
        {canReject && (
          <Button disabled={busy} onClick={() => setMode(mode === "reject" ? "none" : "reject")}>
            Rechazar
          </Button>
        )}
        {canEdit && (
          <Button
            disabled={busy}
            onClick={() => {
              setJson(JSON.stringify(section.content, null, 2));
              setMode(mode === "edit" ? "none" : "edit");
            }}
          >
            Editar (JSON)
          </Button>
        )}
      </div>
      {mode === "reject" && (
        <div className="grid gap-2">
          <select
            className="w-full max-w-md rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          >
            <option value="">Motivo (opcional)</option>
            {REJECT_REASONS.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
          <textarea
            className="min-h-20 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm"
            placeholder="Qué está mal y qué debería considerar el agente (mínimo 10 caracteres)"
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
          />
          <div>
            <Button
              variant="danger"
              disabled={busy || feedback.trim().length < 10}
              onClick={() => reject.mutate({ ...target, feedback, reason: reason || undefined }, done)}
            >
              {busy && <Spinner />} Confirmar rechazo
            </Button>
          </div>
        </div>
      )}
      {mode === "edit" && (
        <div className="grid gap-2">
          <p className="text-xs text-amber-800">
            Limitación del PoC: la edición manual no pasa por los guardrails de D4 (catálogo, citas, culpa a personas).
          </p>
          <textarea
            className="min-h-72 w-full rounded-md border border-border bg-surface p-2 font-mono text-xs"
            value={json}
            onChange={(e) => setJson(e.target.value)}
          />
          <div>
            <Button variant="primary" disabled={busy} onClick={saveEdit}>
              {busy && <Spinner />} Guardar como v{section.version_no + 1}
            </Button>
          </div>
        </div>
      )}
      <ErrorBox error={error} />
    </div>
  );
}
