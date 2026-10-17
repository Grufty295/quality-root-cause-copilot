"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Shell, useUser } from "../components/shell";
import { Badge, Button, Card, Empty, ErrorBox, LevelBadge, Spinner, statusTone } from "../components/ui";
import { api, fmtDate, STATUS_LABEL, type Ncr, type User } from "../lib/api";

export default function NcrsPage() {
  return (
    <Shell>
      <NcrList />
    </Shell>
  );
}

function NcrList() {
  const user = useUser();
  const [ncrs, setNcrs] = useState<Ncr[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(() => {
    api
      .ncrs()
      .then(setNcrs)
      .catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  const canOpen = user.role === "inspector" || user.role === "ingeniero";

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">No conformidades</h1>
          <p className="text-sm text-muted">Solo ves las NCR de tu alcance.</p>
        </div>
        {canOpen && (
          <Button variant="primary" onClick={() => setCreating((v) => !v)}>
            {creating ? "Cancelar" : "Nueva NCR"}
          </Button>
        )}
      </div>
      {creating && <NewNcr user={user} />}
      <ErrorBox error={error} />
      {!ncrs && !error && (
        <p className="flex items-center gap-2 text-sm text-muted">
          <Spinner /> Cargando…
        </p>
      )}
      {ncrs && ncrs.length === 0 && <Empty>No hay NCR en tu alcance.</Empty>}
      {ncrs && ncrs.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-border bg-surface">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="border-b border-border text-left text-xs text-muted">
              <tr>
                <th className="px-3 py-2 font-medium">Código</th>
                <th className="px-3 py-2 font-medium">Planta · línea</th>
                <th className="px-3 py-2 font-medium">Descripción</th>
                <th className="px-3 py-2 font-medium">Nivel</th>
                <th className="px-3 py-2 font-medium">Estado</th>
                <th className="px-3 py-2 font-medium">Alta</th>
              </tr>
            </thead>
            <tbody>
              {ncrs.map((n) => (
                <tr key={n.id} className="border-b border-border last:border-0 hover:bg-zinc-50">
                  <td className="px-3 py-2 font-mono text-xs">
                    <Link href={`/ncrs/${n.id}`} className="font-medium underline-offset-2 hover:underline">
                      {n.code}
                    </Link>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    {n.plant_id} · {n.line_id} · T{n.shift}
                  </td>
                  <td className="max-w-md px-3 py-2">
                    <Link href={`/ncrs/${n.id}`} className="line-clamp-2">
                      {n.description}
                    </Link>
                  </td>
                  <td className="px-3 py-2">
                    <LevelBadge level={n.detected_level} />
                  </td>
                  <td className="px-3 py-2">
                    <Badge tone={statusTone(n.status)}>{STATUS_LABEL[n.status] ?? n.status}</Badge>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-xs text-muted">{fmtDate(n.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function linesOf(user: User): { plant: string; line: string }[] {
  const out: { plant: string; line: string }[] = [];
  for (const s of user.scopes) {
    // Alcance de planta completa: la demo tiene L1 y L2 en JRZ1 y solo L1 en JRZ2.
    const lines = s.line_id ? [s.line_id] : s.plant_id === "JRZ1" ? ["L1", "L2"] : ["L1"];
    for (const l of lines) out.push({ plant: s.plant_id, line: l });
  }
  return out;
}

function NewNcr({ user }: { user: User }) {
  const router = useRouter();
  const options = linesOf(user);
  const [where, setWhere] = useState(options[0] ? `${options[0].plant}|${options[0].line}` : "");
  const [shift, setShift] = useState(1);
  const [description, setDescription] = useState("");
  const [part, setPart] = useState("");
  const [customer, setCustomer] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const [plant_id, line_id] = where.split("|");
    setBusy(true);
    setError(null);
    try {
      const ncr = await api.openNcr({
        plant_id,
        line_id,
        shift,
        description,
        part_number: part || undefined,
        customer_id: customer || undefined,
      });
      router.push(`/ncrs/${ncr.id}`);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  const field = "w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm";
  return (
    <Card title="Nueva no conformidad">
      <form onSubmit={submit} className="grid gap-3 sm:grid-cols-4">
        <label className="grid gap-1 text-xs text-muted">
          Planta · línea
          <select className={field} value={where} onChange={(e) => setWhere(e.target.value)}>
            {options.map((o) => (
              <option key={`${o.plant}|${o.line}`} value={`${o.plant}|${o.line}`}>
                {o.plant} · {o.line}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-xs text-muted">
          Turno
          <select className={field} value={shift} onChange={(e) => setShift(Number(e.target.value))}>
            <option value={1}>T1</option>
            <option value={2}>T2</option>
            <option value={3}>T3</option>
          </select>
        </label>
        <label className="grid gap-1 text-xs text-muted">
          Número de parte (opcional)
          <input className={field} value={part} onChange={(e) => setPart(e.target.value)} placeholder="A7-DRH-2210-M" />
        </label>
        <label className="grid gap-1 text-xs text-muted">
          Cliente (opcional)
          <input className={field} value={customer} onChange={(e) => setCustomer(e.target.value)} placeholder="NOR" />
        </label>
        <label className="grid gap-1 text-xs text-muted sm:col-span-4">
          Descripción del defecto
          <textarea
            className={`${field} min-h-24`}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Qué se encontró, dónde, cuántas piezas, en qué prueba…"
            required
            minLength={10}
          />
        </label>
        <div className="flex items-center gap-3 sm:col-span-4">
          <Button variant="primary" type="submit" disabled={busy}>
            {busy && <Spinner />} Abrir NCR
          </Button>
          <span className="text-xs text-muted">
            El clasificador decide el nivel de confidencialidad al guardar (cliente, parte, datos personales).
          </span>
        </div>
        <div className="sm:col-span-4">
          <ErrorBox error={error} />
        </div>
      </form>
    </Card>
  );
}
