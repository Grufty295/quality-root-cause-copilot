import { fmtDate, type Run } from "../../lib/api";
import { Badge, Empty, statusTone } from "../ui";

export function RunsTable({ runs }: { runs: Run[] }) {
  if (!runs.length) return <Empty>Sin corridas del agente.</Empty>;
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-surface">
      <table className="w-full min-w-[760px] text-sm">
        <thead className="border-b border-border text-left text-xs text-muted">
          <tr>
            <th className="px-3 py-2 font-medium">Inicio</th>
            <th className="px-3 py-2 font-medium">Estado</th>
            <th className="px-3 py-2 font-medium">Disciplinas</th>
            <th className="px-3 py-2 font-medium">Duración</th>
            <th className="px-3 py-2 font-medium">Llamadas</th>
            <th className="px-3 py-2 font-medium">Costo reportado</th>
            <th className="px-3 py-2 font-medium">Bloqueos</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.run_id} className="border-b border-border align-top last:border-0">
              <td className="px-3 py-2 whitespace-nowrap text-xs">{fmtDate(r.started_at)}</td>
              <td className="px-3 py-2">
                <Badge tone={statusTone(r.status)}>{r.status}</Badge>
              </td>
              <td className="px-3 py-2">{r.disciplines.join(", ")}</td>
              <td className="px-3 py-2 whitespace-nowrap">{r.duration_ms ? `${(r.duration_ms / 1000).toFixed(0)} s` : "—"}</td>
              <td className="px-3 py-2">{r.usage.llm_calls ?? "—"}</td>
              <td className="px-3 py-2">
                {r.usage.cost_reported_usd != null ? `$${Number(r.usage.cost_reported_usd).toFixed(4)}` : "—"}
              </td>
              <td className="max-w-sm px-3 py-2 text-xs text-red-700">
                {Object.entries(r.blocked)
                  .map(([d, w]) => `${d}: ${w}`)
                  .join(" · ") || r.error || ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
