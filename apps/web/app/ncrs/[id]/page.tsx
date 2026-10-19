"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Shell, useUser } from "../../components/shell";
import { AnalyzePanel } from "../../components/ncr/analyze-panel";
import { AuditView } from "../../components/ncr/audit-view";
import { NcrHeader } from "../../components/ncr/ncr-header";
import { RunsTable } from "../../components/ncr/runs-table";
import { SectionCard } from "../../components/ncr/section-card";
import { Empty, ErrorBox, Spinner } from "../../components/ui";
import { ApiError, errorText, type Section } from "../../lib/api";
import { useAudit, useNcr, useSections } from "../../lib/queries";
import { useAgentRun, type AgentRun } from "../../lib/use-agent-run";

export default function NcrPage() {
  return (
    <Shell>
      <NcrDetail />
    </Shell>
  );
}

type Tab = "analisis" | "corridas" | "auditoria";

function NcrDetail() {
  const { id } = useParams<{ id: string }>();
  const ncrQuery = useNcr(id);
  const sectionsQuery = useSections(id);
  const auditQuery = useAudit(id);
  const agent = useAgentRun(id);
  const [tab, setTab] = useState<Tab>("analisis");

  const ncr = ncrQuery.data;
  const runs = agent.runs ?? [];
  const sections = sectionsQuery.data ?? [];

  if (ncrQuery.error && !ncr) {
    const missing = ncrQuery.error instanceof ApiError && ncrQuery.error.status === 404;
    return (
      <div className="grid gap-3">
        <ErrorBox error={missing ? "La NCR no existe o no está en tu alcance." : errorText(ncrQuery.error)} />
        <Link href="/ncrs" className="text-sm underline">
          Volver a la lista
        </Link>
      </div>
    );
  }
  if (!ncr) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted">
        <Spinner /> Cargando…
      </p>
    );
  }

  const tabs: [Tab, string][] = [
    ["analisis", "Análisis"],
    ["corridas", `Corridas (${runs.length})`],
    ["auditoria", `Auditoría (${auditQuery.data?.entries.length ?? 0})`],
  ];

  return (
    <div className="grid gap-4">
      <Link href="/ncrs" className="text-xs text-muted hover:underline">
        ← No conformidades
      </Link>
      <NcrHeader ncr={ncr} />
      <ErrorBox error={errorText(sectionsQuery.error ?? agent.runsError ?? auditQuery.error)} />
      <nav className="flex gap-1 border-b border-border">
        {tabs.map(([t, label]) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${tab === t ? "border-zinc-900 font-medium" : "border-transparent text-muted hover:text-foreground"}`}
          >
            {label}
          </button>
        ))}
      </nav>
      {tab === "analisis" && <Analysis ncrId={ncr.id} sections={sections} agent={agent} />}
      {tab === "corridas" && <RunsTable runs={runs} />}
      {tab === "auditoria" && <AuditView audit={auditQuery.data} />}
    </div>
  );
}

function Analysis({ ncrId, sections, agent }: { ncrId: string; sections: Section[]; agent: AgentRun }) {
  const user = useUser();
  const byDiscipline = Object.fromEntries(sections.map((s) => [s.discipline, s])) as Partial<Record<string, Section>>;
  return (
    <div className="grid gap-4">
      {user.role === "ingeniero" && <AnalyzePanel sections={sections} agent={agent} />}
      {user.role === "inspector" && (
        <p className="text-xs text-muted">
          Vista de solo lectura: si ves una desviación en el borrador, avísale al ingeniero para que ajuste el análisis.
        </p>
      )}
      {sections.length === 0 && <Empty>Todavía no hay borradores para esta NCR.</Empty>}
      {["D2", "D4"].map((d) => {
        const section = byDiscipline[d];
        return section ? <SectionCard key={d} ncrId={ncrId} section={section} /> : null;
      })}
    </div>
  );
}
