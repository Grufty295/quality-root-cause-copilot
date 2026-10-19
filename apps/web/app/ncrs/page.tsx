"use client";

import Link from "next/link";
import { useState } from "react";
import { Shell, useUser } from "../components/shell";
import { Badge, Button, Card, ErrorBox, Spinner, statusTone } from "../components/ui";
import { errorText, fmtDate, ROLE_LABEL, STATUS_LABEL } from "../lib/api";
import { useDemoUsers, useLogin, useNcrs, useOpenNcr } from "../lib/queries";

export default function NcrsPage() {
  return (
    <Shell>
      <NcrsList />
    </Shell>
  );
}

function NcrsList() {
  const user = useUser();
  const ncrsQuery = useNcrs();
  const demoUsers = useDemoUsers().data ?? [];
  const openNcr = useOpenNcr();
  const login = useLogin();

  const [openModal, setOpenModal] = useState(false);
  const [plantId, setPlantId] = useState("JRZ1");
  const [lineId, setLineId] = useState("L1");
  const [shift, setShift] = useState(1);
  const [description, setDescription] = useState("");
  const [partNumber, setPartNumber] = useState("");
  const [customerId, setCustomerId] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);

  const ncrs = ncrsQuery.data ?? [];
  const loading = ncrsQuery.isPending;
  const submitting = openNcr.isPending;
  const error = validationError ?? errorText(ncrsQuery.error ?? openNcr.error ?? login.error);

  const handleOpen = (e: React.FormEvent) => {
    e.preventDefault();
    if (description.trim().length < 10) {
      setValidationError("La descripción debe tener al menos 10 caracteres.");
      return;
    }
    setValidationError(null);
    openNcr.mutate(
      {
        plant_id: plantId,
        line_id: lineId,
        shift,
        description,
        part_number: partNumber || undefined,
        customer_id: customerId || undefined,
      },
      {
        onSuccess: () => {
          setOpenModal(false);
          setDescription("");
          setPartNumber("");
          setCustomerId("");
        },
      },
    );
  };

  const handleSwitchUser = (username: string) => login.mutate(username);

  const canOpen = user.role === "inspector" || user.role === "ingeniero";

  return (
    <div className="grid gap-6">
      {/* Selector de perfiles de demo */}
      <div className="flex flex-wrap items-center justify-between gap-3 bg-secondary/40 border border-border p-3 rounded-lg">
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono uppercase text-muted">Sesión actual:</span>
          <Badge tone="violet">{user.display_name} ({ROLE_LABEL[user.role]})</Badge>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-muted mr-1">Cambiar demo:</span>
          {demoUsers.slice(0, 6).map((u) => (
            <button
              key={u.username}
              onClick={() => handleSwitchUser(u.username)}
              className={`text-xs px-2 py-1 rounded border font-mono transition-colors ${
                u.username === user.username
                  ? "bg-primary text-primary-foreground border-primary font-bold"
                  : "bg-background border-border hover:border-primary/50 text-foreground"
              }`}
              title={`${u.display_name} — ${u.role}`}
            >
              {u.username}
            </button>
          ))}
        </div>
      </div>

      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">No Conformidades (NCR)</h1>
          <p className="text-sm text-muted">Gestión de calidad 8D para plantas Cablenova Juárez (JRZ1 y JRZ2)</p>
        </div>
        {canOpen && (
          <Button onClick={() => setOpenModal(true)}>+ Abrir Nueva NCR</Button>
        )}
      </div>

      <ErrorBox error={error} />

      {loading ? (
        <p className="flex items-center gap-2 text-sm text-muted">
          <Spinner /> Cargando registros…
        </p>
      ) : ncrs.length === 0 ? (
        <Card>
          <p className="text-sm text-muted text-center py-6">No hay no conformidades registradas en tu alcance.</p>
        </Card>
      ) : (
        <div className="grid gap-3">
          {ncrs.map((n) => (
            <Link
              key={n.id}
              href={`/ncrs/${n.id}`}
              className="block rounded-lg border border-border bg-surface p-4 transition-all hover:border-primary/50 hover:shadow-sm"
            >
              <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm font-bold text-primary">{n.code}</span>
                  <Badge tone={statusTone(n.status)}>{STATUS_LABEL[n.status] ?? n.status}</Badge>
                  <span className="text-xs font-mono bg-secondary px-2 py-0.5 rounded text-muted">{n.plant_id} · {n.line_id}</span>
                </div>
                <span className="text-xs text-muted">{fmtDate(n.created_at)}</span>
              </div>
              <p className="text-sm line-clamp-2 text-foreground mb-2">{n.description}</p>
              <div className="flex gap-4 text-xs font-mono text-muted">
                {n.part_number && <span>Parte: {n.part_number}</span>}
                {n.customer_id && <span>Cliente: {n.customer_id}</span>}
                <span>Turno: T{n.shift}</span>
              </div>
            </Link>
          ))}
        </div>
      )}

      {openModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className="w-full max-w-lg bg-surface border border-border rounded-lg p-6 shadow-xl">
            <h3 className="text-lg font-bold mb-4">Abrir Nueva No Conformidad (NCR)</h3>
            <form onSubmit={handleOpen} className="grid gap-3">
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-xs font-mono uppercase text-muted">Planta</label>
                  <select
                    className="w-full rounded border border-border bg-surface p-2 text-sm"
                    value={plantId}
                    onChange={(e) => setPlantId(e.target.value)}
                  >
                    <option value="JRZ1">JRZ1 (Juárez 1)</option>
                    <option value="JRZ2">JRZ2 (Juárez 2)</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs font-mono uppercase text-muted">Línea</label>
                  <select
                    className="w-full rounded border border-border bg-surface p-2 text-sm"
                    value={lineId}
                    onChange={(e) => setLineId(e.target.value)}
                  >
                    <option value="L1">Línea 1</option>
                    <option value="L2">Línea 2</option>
                    <option value="L3">Línea 3</option>
                    <option value="L4">Línea 4</option>
                  </select>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-xs font-mono uppercase text-muted">Turno</label>
                  <select
                    className="w-full rounded border border-border bg-surface p-2 text-sm"
                    value={shift}
                    onChange={(e) => setShift(Number(e.target.value))}
                  >
                    <option value={1}>Turno 1</option>
                    <option value={2}>Turno 2</option>
                    <option value={3}>Turno 3</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs font-mono uppercase text-muted">Número de Parte</label>
                  <input
                    className="w-full rounded border border-border bg-surface p-2 text-sm font-mono"
                    placeholder="P-TERM-001"
                    value={partNumber}
                    onChange={(e) => setPartNumber(e.target.value)}
                  />
                </div>
              </div>
              <div>
                <label className="text-xs font-mono uppercase text-muted">Cliente (opcional)</label>
                <input
                  className="w-full rounded border border-border bg-surface p-2 text-sm"
                  placeholder="CUST-A"
                  value={customerId}
                  onChange={(e) => setCustomerId(e.target.value)}
                />
              </div>
              <div>
                <label className="text-xs font-mono uppercase text-muted">Descripción del Defecto (Mín. 10 caracteres)</label>
                <textarea
                  className="w-full rounded border border-border bg-surface p-2 text-sm min-h-[100px]"
                  placeholder="Detalle de la falla observada en piso..."
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </div>
              <div className="flex justify-end gap-2 mt-2">
                <Button type="button" variant="secondary" onClick={() => setOpenModal(false)}>Cancelar</Button>
                <Button type="submit" disabled={submitting}>{submitting ? "Abriendo..." : "Crear NCR"}</Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
