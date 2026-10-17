"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { D2View, D4View } from "../../components/drafts";
import { Shell, useUser } from "../../components/shell";
import { Badge, Button, Card, Empty, ErrorBox, LevelBadge, Spinner, statusTone } from "../../components/ui";
import {
  api,
  ApiError,
  fmtDate,
  REJECT_REASONS,
  STATUS_LABEL,
  type Audit,
  type D2Content,
  type D4Content,
  type Ncr,
  type Run,
  type Section,
} from "../../lib/api";

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
  const [ncr, setNcr] = useState<Ncr | null>(null);
  const [sections, setSections] = useState<Section[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [audit, setAudit] = useState<Audit | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("analisis");

  const reload = useCallback(
    () =>
      Promise.all([api.ncr(id), api.sections(id), api.runs(id), api.audit(id)]).then(
        ([n, s, r, a]) => {
          setNcr(n);
          setSections(s);
          setRuns(r);
          setAudit(a);
          setError(null);
        },
        (e) =>
          setError(
            e instanceof ApiError && e.status === 404
              ? "La NCR no existe o no está en tu alcance."
              : (e as Error).message,
          ),
      ),
    [id],
  );

  useEffect(() => {
    let alive = true;
    Promise.all([api.ncr(id), api.sections(id), api.runs(id), api.audit(id)]).then(
      ([n, s, r, a]) => {
        if (!alive) return;
        setNcr(n);
        setSections(s);
        setRuns(r);
        setAudit(a);
      },
      (e) => {
        if (!alive) return;
        setError(
          e instanceof ApiError && e.status === 404
            ? "La NCR no existe o no está en tu alcance."
            : (e as Error).message,
        );
      },
    );
    return () => {
      alive = false;
    };
  }, [id]);

  if (error && !ncr) {
    return (
      <div className="grid gap-3">
        <ErrorBox error={error} />
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
    ["auditoria", `Auditoría (${audit?.entries.length ?? 0})`],
  ];

  return (
    <div className="grid gap-4">
      <Link href="/ncrs" className="text-xs text-muted hover:underline">
        ← No conformidades
      </Link>
      <NcrHeader ncr={ncr} />
      <ErrorBox error={error} />
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
      {tab === "analisis" && <Analysis ncr={ncr} sections={sections} runs={runs} onChange={reload} />}
      {tab === "corridas" && <Runs runs={runs} />}
      {tab === "auditoria" && <AuditView audit={audit} />}
    </div>
  );
}

function NcrHeader({ ncr }: { ncr: Ncr }) {
  return (
    <Card
      title={
        <span className="flex flex-wrap items-center gap-2">
          <span className="font-mono">{ncr.code}</span>
          <Badge tone={statusTone(ncr.status)}>{STATUS_LABEL[ncr.status] ?? ncr.status}</Badge>
        </span>
      }
      actions={<LevelBadge level={ncr.detected_level} />}
    >
      <p className="text-sm leading-relaxed">{ncr.description}</p>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-5">
        <Meta k="Planta · línea" v={`${ncr.plant_id} · ${ncr.line_id}`} />
        <Meta k="Turno" v={`T${ncr.shift}`} />
        <Meta k="Parte" v={ncr.part_number ?? "—"} />
        <Meta k="Cliente" v={ncr.customer_id ?? "—"} />
        <Meta k="Alta" v={fmtDate(ncr.created_at)} />
      </dl>
      {!!ncr.classification_reasons?.length && (
        <p className="mt-3 text-xs text-muted">
          Por qué es {ncr.detected_level}: {ncr.classification_reasons.join("; ")}
          {ncr.contains_pii ? " · contiene datos personales (se seudonimizan antes de ir al modelo)" : ""}
        </p>
      )}
    </Card>
  );
}

function Meta({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <dt className="text-muted">{k}</dt>
      <dd className="font-medium">{v}</dd>
    </div>
  );
}

// ------------------------------------------------------------------ análisis y revisión

function Analysis({
  ncr,
  sections,
  runs,
  onChange,
}: {
  ncr: Ncr;
  sections: Section[];
  runs: Run[];
  onChange: () => Promise<void>;
}) {
  const user = useUser();
  const byD = Object.fromEntries(sections.map((s) => [s.discipline, s])) as Partial<Record<string, Section>>;
  const order = ["D2", "D4"];
  return (
    <div className="grid gap-4">
      {user.role === "ingeniero" && <AnalyzePanel ncr={ncr} sections={sections} runs={runs} onDone={onChange} />}
      {user.role === "inspector" && (
        <p className="text-xs text-muted">
          Vista de solo lectura: si ves una desviación en el borrador, avísale al ingeniero para que ajuste el análisis.
        </p>
      )}
      {sections.length === 0 && <Empty>Todavía no hay borradores para esta NCR.</Empty>}
      {order.map((d) => {
        const s = byD[d];
        return s ? <SectionCard key={d} ncrId={ncr.id} section={s} onChange={onChange} /> : null;
      })}
    </div>
  );
}

const KIND_LABEL: Record<Section["kind"], string> = {
  agente: "borrador del agente",
  edicion: "editada",
  aprobacion: "aprobada",
  rechazo: "rechazada",
};

function SectionCard({ ncrId, section, onChange }: { ncrId: string; section: Section; onChange: () => Promise<void> }) {
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
            <D4View content={section.content as unknown as D4Content} />
          ) : section.discipline === "D2" ? (
            <D2View content={section.content as unknown as D2Content} />
          ) : (
            <pre className="overflow-x-auto text-xs">{JSON.stringify(section.content, null, 2)}</pre>
          ))}
        <ReviewBar ncrId={ncrId} section={section} onChange={onChange} />
      </div>
    </Card>
  );
}

function ReviewBar({ ncrId, section, onChange }: { ncrId: string; section: Section; onChange: () => Promise<void> }) {
  const user = useUser();
  const [mode, setMode] = useState<"none" | "reject" | "edit">("none");
  const [feedback, setFeedback] = useState("");
  const [reason, setReason] = useState("");
  const [json, setJson] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const final = section.kind === "aprobacion";
  const canEdit = user.role === "ingeniero" && !final && section.content !== null;
  const canReject = (user.role === "ingeniero" || user.role === "gerente") && !final && section.kind !== "rechazo";
  const canApprove = user.role === "gerente" && !final && section.kind !== "rechazo" && section.content !== null;
  if (!canEdit && !canReject && !canApprove) return null;

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      setMode("none");
      setFeedback("");
      setReason("");
      await onChange();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-3 border-t border-border pt-3">
      <div className="flex flex-wrap gap-2">
        {canApprove && (
          <Button variant="primary" disabled={busy} onClick={() => act(() => api.approve(ncrId, section.discipline, section.version_no))}>
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
              onClick={() =>
                act(() => api.reject(ncrId, section.discipline, section.version_no, feedback, reason || undefined))
              }
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
            <Button
              variant="primary"
              disabled={busy}
              onClick={() =>
                act(async () => {
                  let parsed: unknown;
                  try {
                    parsed = JSON.parse(json);
                  } catch {
                    throw new Error("El JSON no es válido");
                  }
                  return api.edit(ncrId, section.discipline, section.version_no, parsed);
                })
              }
            >
              {busy && <Spinner />} Guardar como v{section.version_no + 1}
            </Button>
          </div>
        </div>
      )}
      <ErrorBox error={error} />
    </div>
  );
}

// ------------------------------------------------------------------ correr el agente

const POLL_MS = 4000;
const GIVE_UP_MS = 15 * 60 * 1000;

function AnalyzePanel({
  ncr,
  sections,
  runs,
  onDone,
}: {
  ncr: Ncr;
  sections: Section[];
  runs: Run[];
  onDone: () => Promise<void>;
}) {
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [last, setLast] = useState<Run | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  // Una corrida "en_curso" de hace más que el límite de espera quedó huérfana (API reiniciado,
  // contenedor detenido): no se sigue, o el botón se queda en "Analizando…" para siempre.
  const [mountedAt] = useState(() => Date.now());
  const active =
    runs.find((r) => r.status === "en_curso" && mountedAt - new Date(r.started_at).getTime() < GIVE_UP_MS) ?? null;
  const following = useRef<string | null>(null);
  const running = startedAt !== null || active !== null;
  const generable = sections.length === 0 || sections.some((s) => s.kind === "rechazo") || sections.length < 2;

  const stop = useCallback(() => {
    if (timer.current) clearInterval(timer.current);
    timer.current = null;
    setStartedAt(null);
  }, []);

  useEffect(() => () => stop(), [stop]);

  const poll = useCallback(
    (since: number) => {
      if (timer.current) clearInterval(timer.current);
      timer.current = setInterval(async () => {
        setElapsed(Date.now() - since);
        try {
          const rs = await api.runs(ncr.id);
          const mine = rs.find((r) => new Date(r.started_at).getTime() >= since - 10_000);
          if (mine && mine.status !== "en_curso") {
            setLast(mine);
            stop();
            await onDone();
          }
        } catch {
          /* la siguiente vuelta reintenta */
        }
        if (Date.now() - since > GIVE_UP_MS) {
          stop();
          setError("La corrida no terminó en 15 minutos; revisa la pestaña Corridas.");
        }
      }, POLL_MS);
    },
    [ncr.id, onDone, stop],
  );

  // Si al entrar ya hay una corrida en curso (otra pestaña, recarga), se sigue.
  useEffect(() => {
    if (active && startedAt === null && following.current !== active.run_id) {
      following.current = active.run_id;
      poll(new Date(active.started_at).getTime());
    }
  }, [active, startedAt, poll]);

  async function start() {
    const since = Date.now();
    setError(null);
    setLast(null);
    setStartedAt(since);
    setElapsed(0);
    poll(since);
    // El análisis tarda minutos: no se espera la respuesta, se sigue por /runs.
    api.analyze(ncr.id, crypto.randomUUID()).catch((e) => {
      // Una respuesta HTTP del API es un error real (400, 403, 503…): se muestra y se detiene.
      // Solo se sigue esperando si la conexión se cortó o el proxy venció (504/502) mientras
      // la corrida seguía viva: ahí manda /runs.
      if (e instanceof ApiError && e.status !== 502 && e.status !== 504) {
        stop();
        setError(
          e.status === 503
            ? `El agente no está disponible: ${e.message}. Revisa la configuración del modelo en el servidor (logs del API).`
            : e.message,
        );
      }
    });
  }

  const mmss = `${Math.floor(elapsed / 60000)}:${String(Math.floor((elapsed % 60000) / 1000)).padStart(2, "0")}`;

  return (
    <Card
      title="Agente"
      actions={
        <Button variant="primary" onClick={start} disabled={running || !generable}>
          {running && <Spinner />} {running ? `Analizando… ${mmss}` : "Correr análisis D2 + D4"}
        </Button>
      }
    >
      <div className="grid gap-2 text-sm">
        {!running && !generable && (
          <p className="text-muted">
            Ya hay borradores sin revisar. El agente solo regenera una sección si no tiene borrador o si fue rechazada.
          </p>
        )}
        {!running && generable && (
          <p className="text-muted">
            El agente reúne datos de la línea, busca en los 8D y documentos de control que tu alcance permite, y
            propone D2 y D4 con cada afirmación citada. Tarda de 3 a 6 minutos.
          </p>
        )}
        {running && (
          <p className="text-muted">
            Corriendo. Puedes cambiar de pestaña; el resultado aparece aquí al terminar.
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

// ------------------------------------------------------------------ corridas y auditoría

function Runs({ runs }: { runs: Run[] }) {
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

function AuditView({ audit }: { audit: Audit | null }) {
  if (!audit) return <Empty>Sin datos de auditoría.</Empty>;
  return (
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
        Una fila por llamada al modelo. Se guarda nivel, destino, modelo, redacción y costo; nunca el prompt ni la
        respuesta. La base rechaza cualquier fila confidencial con destino «api».
      </p>
      {!audit.entries.length && <Empty>Sin llamadas al modelo sobre esta NCR.</Empty>}
      {!!audit.entries.length && (
        <div className="overflow-x-auto rounded-lg border border-border bg-surface">
          <table className="w-full min-w-[880px] text-sm">
            <thead className="border-b border-border text-left text-xs text-muted">
              <tr>
                <th className="px-3 py-2 font-medium">Hora</th>
                <th className="px-3 py-2 font-medium">Etapa</th>
                <th className="px-3 py-2 font-medium">Nivel</th>
                <th className="px-3 py-2 font-medium">Destino</th>
                <th className="px-3 py-2 font-medium">Modelo</th>
                <th className="px-3 py-2 font-medium">Redacción</th>
                <th className="px-3 py-2 font-medium">Tokens</th>
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
                      <span className="block text-[11px] text-amber-800" title="Local simulado con OpenRouter: solo con datos ficticios">
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
  );
}
