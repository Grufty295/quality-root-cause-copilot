import { fmtDate, type Audit } from "../../lib/api";
import { Badge, Card, Empty, LevelBadge } from "../ui";

export function AuditView({ audit }: { audit: Audit | null | undefined }) {
  if (!audit) return <Empty>Sin datos de auditoría.</Empty>;
  return (
    <div className="grid gap-6">
      <Card title="Trazabilidad y Actividad (¿Quién lo hizo?)">
        {!audit.activity?.length ? (
          <Empty>Sin actividad registrada.</Empty>
        ) : (
          <div className="grid gap-3">
            {audit.activity.map((act, idx) => (
              <div key={idx} className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 p-3 bg-secondary/40 rounded border border-border text-sm">
                <div className="flex items-center gap-3">
                  <Badge tone={act.actor_role === "gerente" ? "green" : act.actor_role === "ingeniero" ? "blue" : "violet"}>
                    {act.actor_role ?? "sistema"}
                  </Badge>
                  <div>
                    <span className="font-bold font-mono">{act.actor ?? "Sistema"}</span>
                    <span className="text-muted text-xs ml-2">({act.kind})</span>
                    {act.discipline && <span className="ml-2 font-mono text-xs bg-primary/10 text-primary px-1.5 py-0.5 rounded">{act.discipline} v{act.version_no}</span>}
                    {act.detail && <p className="text-xs text-foreground mt-1 bg-background/50 p-1.5 rounded border border-border/50">Retroalimentación: {act.detail}</p>}
                    {act.reason && <p className="text-xs text-red-600 mt-0.5 font-mono">Motivo: {act.reason}</p>}
                  </div>
                </div>
                <span className="text-xs text-muted whitespace-nowrap">{fmtDate(act.at)}</span>
              </div>
            ))}
          </div>
        )}
      </Card>

      <div className="grid gap-3">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Badge tone={audit.chain_ok ? "green" : "red"}>
            {audit.chain_ok ? "Cadena de hashes íntegra" : "Cadena de hashes ROTA"}
          </Badge>
          <span className="text-xs text-muted">
            {audit.chain_checked} registros verificados en todo el log · cabeza{" "}
            <span className="font-mono">{audit.head_hash?.slice(0, 16)}…</span>
          </span>
        </div>
        <p className="text-xs text-muted">
          Una llamada al modelo por fila. Se guarda nivel, destino, modelo, redacción, costo y tokens; nunca el prompt ni la
          respuesta. La base rechaza cualquier fila confidencial con destino «api».
        </p>
        {!audit.entries.length && <Empty>Sin llamadas al modelo sobre esta NCR.</Empty>}
        {!!audit.entries.length && (
          <div className="overflow-x-auto rounded-lg border border-border bg-surface">
            <table className="w-full min-w-[940px] text-sm">
              <thead className="border-b border-border text-left text-xs text-muted">
                <tr>
                  <th className="px-3 py-2 font-medium">Hora</th>
                  <th className="px-3 py-2 font-medium">Etapa</th>
                  <th className="px-3 py-2 font-medium">Nivel</th>
                  <th className="px-3 py-2 font-medium">Destino</th>
                  <th className="px-3 py-2 font-medium">Modelo</th>
                  <th className="px-3 py-2 font-medium">Redacción</th>
                  <th className="px-3 py-2 font-medium">Tokens (In → Out)</th>
                  <th className="px-3 py-2 font-medium">Costo (USD)</th>
                  <th className="px-3 py-2 font-medium">Resultado</th>
                  <th className="px-3 py-2 font-medium">Hash</th>
                </tr>
              </thead>
              <tbody>
                {audit.entries.map((e) => (
                  <tr key={e.id} className="border-b border-border align-top last:border-0">
                    <td className="px-3 py-2 whitespace-nowrap text-xs">{fmtDate(e.created_at)}</td>
                    <td className="px-3 py-2">
                      {e.stage}
                      {e.tier ? <span className="text-xs text-muted"> · {e.tier}</span> : null}
                    </td>
                    <td className="px-3 py-2">
                      <LevelBadge level={e.detected_level} />
                    </td>
                    <td className="px-3 py-2">
                      <Badge tone={e.destination === "local" ? "violet" : "neutral"}>{e.destination}</Badge>
                      {e.simulated && (
                        <span className="block text-[11px] text-amber-800" title="Local simulado con OpenRouter">
                          simulado
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      <div className="font-mono">{e.model}</div>
                      <div className="text-muted">{e.provider}</div>
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {[e.redaction_applied && "redactado", e.pseudonymized && "seudónimos"].filter(Boolean).join(" · ") || "—"}
                      {e.redactions && <div className="text-muted">{e.redactions}</div>}
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap text-xs">
                      {e.tokens_in ?? "—"} → {e.tokens_out ?? "—"}
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap text-xs font-mono">
                      {e.cost_usd != null ? `$${Number(e.cost_usd).toFixed(5)}` : "—"}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      <Badge tone={e.outcome === "ok" ? "green" : e.outcome === "blocked" ? "amber" : "red"}>
                        {e.outcome ?? "—"}
                      </Badge>
                      {e.error && <div className="text-red-700">{e.error}</div>}
                      {e.finish_reason && e.finish_reason !== "stop" && <div className="text-amber-800">{e.finish_reason}</div>}
                    </td>
                    <td className="px-3 py-2 font-mono text-xs text-muted">{e.hash}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
