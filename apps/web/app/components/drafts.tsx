"use client";

import { useState } from "react";
import { Button, ErrorBox } from "./ui";
import { errorText, type Section } from "../lib/api";
import { useEditSection } from "../lib/queries";

/** Cada campo 5W2H llega como texto o como `{ texto }`. */
type CampoD2 = string | { texto?: string; [k: string]: unknown } | null | undefined;
type D2Content = Record<string, CampoD2>;

/** Tarjeta de causa de D4. El editor anterior escribía `descripcion`/`hipotesis`; hoy el API usa `explicacion`. */
type Causa = {
  codigo?: string;
  descripcion?: string;
  hipotesis?: string;
  explicacion?: string;
  evidencia?: unknown;
  [k: string]: unknown;
};
type D4Content = { causas_ocurrencia?: Causa[]; causa_no_deteccion?: Causa | null; [k: string]: unknown };

export function D2View({
  section,
  ncrId,
}: {
  section: Section;
  ncrId: string;
}) {
  const content = (section.content || {}) as D2Content;
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<D2Content>(content);
  const edit = useEditSection(ncrId);
  const saving = edit.isPending;
  const error = errorText(edit.error);

  const handleSave = () =>
    edit.mutate(
      { discipline: "D2", version: section.version_no, content: form },
      { onSuccess: () => setEditing(false) },
    );

  const getTexto = (field: string) => {
    const val = form[field];
    if (typeof val === "string") return val;
    return val?.texto || "";
  };

  const setTexto = (field: string, text: string) => {
    const val = form[field];
    const prev = typeof val === "object" && val !== null ? val : {};
    setForm({ ...form, [field]: { ...prev, texto: text } });
  };

  return (
    <div className="grid gap-3">
      <div className="flex justify-between items-center">
        <span className="text-xs font-mono text-muted">Editor Estructurado (5W2H) · {section.author ? `Editado por ${section.author}` : "Generado por Agente"}</span>
        {section.kind !== "aprobacion" && !editing && (
          <Button variant="secondary" onClick={() => setEditing(true)}>Editar</Button>
        )}
      </div>

      <ErrorBox error={error} />

      {!editing ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
          {(["que", "donde", "cuando", "quien", "por_que", "como", "cuanto"] as const).map((field) => (
            <div key={field} className={`p-3 bg-secondary/50 rounded border border-border ${field === "por_que" ? "md:col-span-2" : ""}`}>
              <strong className="block text-xs uppercase font-mono text-muted mb-1">{field.replace("_", " ")}</strong>
              <p>{getTexto(field) || "Sin definir"}</p>
            </div>
          ))}
        </div>
      ) : (
        <div className="grid gap-3">
          {(["que", "donde", "cuando", "quien", "por_que", "como", "cuanto"] as const).map((field) => (
            <div key={field} className="grid gap-1">
              <label className="text-xs font-mono uppercase text-muted">{field.replace("_", " ")}</label>
              <textarea
                className="w-full bg-background border border-border rounded p-2 text-sm focus:outline-none focus:border-primary"
                rows={2}
                value={getTexto(field)}
                onChange={(e) => setTexto(field, e.target.value)}
              />
            </div>
          ))}
          <div className="flex gap-2 mt-2">
            <Button disabled={saving} onClick={handleSave}>{saving ? "Guardando..." : "Guardar Cambios"}</Button>
            <Button variant="secondary" onClick={() => setEditing(false)}>Cancelar</Button>
          </div>
        </div>
      )}
    </div>
  );
}

/** El editor anterior escribía `descripcion` e `hipotesis` junto a `explicacion`; el API ya no las acepta. */
function withoutLegacyKeys(content: D4Content) {
  const clean = (causa: Causa) =>
    Object.fromEntries(Object.entries(causa).filter(([key]) => key !== "descripcion" && key !== "hipotesis"));
  return {
    ...content,
    causas_ocurrencia: (content.causas_ocurrencia || []).map(clean),
    causa_no_deteccion: content.causa_no_deteccion ? clean(content.causa_no_deteccion) : null,
  };
}

export function D4View({
  section,
  ncrId,
}: {
  section: Section;
  ncrId: string;
}) {
  const content = (section.content || {}) as D4Content;
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<D4Content>(JSON.parse(JSON.stringify(content || { causas_ocurrencia: [], causa_no_deteccion: null })));
  const edit = useEditSection(ncrId);
  const saving = edit.isPending;
  const error = errorText(edit.error);

  const handleSave = () =>
    edit.mutate(
      { discipline: "D4", version: section.version_no, content: withoutLegacyKeys(form) },
      { onSuccess: () => setEditing(false) },
    );

  const renderEvidencia = (evidencia: unknown) => {
    if (!evidencia) return "Ninguna";
    if (Array.isArray(evidencia)) {
      return evidencia.map((e) => (typeof e === "string" ? e : e.texto || e.id || JSON.stringify(e))).join(", ");
    }
    if (typeof evidencia === "object") return (evidencia as { texto?: string }).texto || JSON.stringify(evidencia);
    return String(evidencia);
  };

  return (
    <div className="grid gap-4">
      <div className="flex justify-between items-center">
        <span className="text-xs font-mono text-muted">Tarjetas de Causas Raíz · {section.author ? `Editado por ${section.author}` : "Generado por Agente"}</span>
        {section.kind !== "aprobacion" && !editing && (
          <Button variant="secondary" onClick={() => setEditing(true)}>Editar Tarjetas</Button>
        )}
      </div>

      <ErrorBox error={error} />

      {!editing ? (
        <div className="grid gap-4">
          <div>
            <h4 className="text-xs font-mono uppercase text-muted mb-2">Causas de Ocurrencia (RC)</h4>
            <div className="grid gap-3">
              {(content.causas_ocurrencia || []).map((c: Causa, idx: number) => (
                <div key={idx} className="p-3 bg-secondary/50 rounded border border-border">
                  <div className="flex justify-between items-center mb-1">
                    <span className="font-mono text-xs font-bold px-2 py-0.5 bg-primary/20 text-primary rounded">{c.codigo}</span>
                    <span className="text-xs text-muted">Evidencia: {renderEvidencia(c.evidencia)}</span>
                  </div>
                  <p className="text-sm font-medium">{c.descripcion || c.hipotesis || c.explicacion}</p>
                </div>
              ))}
            </div>
          </div>

          <div>
            <h4 className="text-xs font-mono uppercase text-muted mb-2">Causa de No Detección (ND)</h4>
            {content.causa_no_deteccion ? (
              <div className="p-3 bg-secondary/50 rounded border border-border">
                <div className="flex justify-between items-center mb-1">
                  <span className="font-mono text-xs font-bold px-2 py-0.5 bg-amber-500/20 text-amber-400 rounded">{content.causa_no_deteccion.codigo}</span>
                  <span className="text-xs text-muted">Evidencia: {renderEvidencia(content.causa_no_deteccion.evidencia)}</span>
                </div>
                <p className="text-sm font-medium">{content.causa_no_deteccion.descripcion || content.causa_no_deteccion.hipotesis || content.causa_no_deteccion.explicacion}</p>
              </div>
            ) : (
              <p className="text-xs text-muted">Sin causa de no detección registrada.</p>
            )}
          </div>
        </div>
      ) : (
        <div className="grid gap-4">
          <div>
            <h4 className="text-xs font-mono uppercase text-muted mb-2">Causas de Ocurrencia (RC)</h4>
            {(form.causas_ocurrencia || []).map((c: Causa, idx: number) => (
              <div key={idx} className="p-3 bg-background border border-border rounded mb-3 grid gap-2">
                <div className="flex gap-2">
                  <input
                    className="w-32 bg-secondary border border-border rounded p-1 text-sm font-mono"
                    placeholder="RC-01"
                    value={c.codigo || ""}
                    onChange={(e) => {
                      const copy = [...(form.causas_ocurrencia ?? [])];
                      copy[idx] = { ...copy[idx], codigo: e.target.value };
                      setForm({ ...form, causas_ocurrencia: copy });
                    }}
                  />
                  <input
                    className="flex-1 bg-secondary border border-border rounded p-1 text-sm"
                    placeholder="Descripción de la causa..."
                    value={c.descripcion || c.hipotesis || c.explicacion || ""}
                    onChange={(e) => {
                      const val = e.target.value;
                      const copy = [...(form.causas_ocurrencia ?? [])];
                      copy[idx] = { ...copy[idx], explicacion: val };
                      setForm({ ...form, causas_ocurrencia: copy });
                    }}
                  />
                </div>
              </div>
            ))}
          </div>

          <div>
            <h4 className="text-xs font-mono uppercase text-muted mb-2">Causa de No Detección (ND)</h4>
            {form.causa_no_deteccion && (
              <div className="p-3 bg-background border border-border rounded grid gap-2">
                <div className="flex gap-2">
                  <input
                    className="w-32 bg-secondary border border-border rounded p-1 text-sm font-mono"
                    placeholder="ND-01"
                    value={form.causa_no_deteccion.codigo || ""}
                    onChange={(e) => {
                      setForm({
                        ...form,
                        causa_no_deteccion: { ...form.causa_no_deteccion, codigo: e.target.value },
                      });
                    }}
                  />
                  <input
                    className="flex-1 bg-secondary border border-border rounded p-1 text-sm"
                    placeholder="Descripción de no detección..."
                    value={form.causa_no_deteccion.descripcion || form.causa_no_deteccion.hipotesis || form.causa_no_deteccion.explicacion || ""}
                    onChange={(e) => {
                      const val = e.target.value;
                      setForm({
                        ...form,
                        causa_no_deteccion: { ...form.causa_no_deteccion, explicacion: val },
                      });
                    }}
                  />
                </div>
              </div>
            )}
          </div>

          <div className="flex gap-2 mt-2">
            <Button disabled={saving} onClick={handleSave}>{saving ? "Guardando..." : "Guardar Cambios"}</Button>
            <Button variant="secondary" onClick={() => setEditing(false)}>Cancelar</Button>
          </div>
        </div>
      )}
    </div>
  );
}
