// Cliente de la API. El navegador solo habla con Next.js: /api/* se reenvía a FastAPI
// (next.config.ts), así la cookie de sesión es del mismo origen y no hay CORS.

export type Role = "inspector" | "ingeniero" | "gerente" | "auditor";

export interface User {
  id: string;
  username: string;
  display_name: string;
  role: Role;
  scopes: { plant_id: string; line_id: string | null }[];
}

export interface Ncr {
  id: string;
  code: string;
  plant_id: string;
  line_id: string;
  shift: number;
  part_number: string | null;
  customer_id: string | null;
  description: string;
  detected_level: string | null;
  contains_pii: boolean | null;
  classification_reasons: string[] | null;
  status: string;
  opened_by: string;
  created_at: string;
}

export interface Hecho {
  texto: string;
  fuentes: string[];
}

export interface FuenteRef {
  tipo: "fragmento" | "herramienta" | "reporte";
  documento?: string | null;
  seccion?: string | null;
  herramienta?: string | null;
  parametros?: Record<string, string> | null;
  nivel?: string | null;
}

export interface Causa {
  codigo: string;
  explicacion: string;
  evidencia: Hecho[];
  pregunta_confirmacion: string;
  evidencia_contradictoria?: Hecho[];
  refutaria?: string | null;
  dato_faltante?: string | null;
  respaldo?: "caso" | "solo_catalogo";
}

export interface D4Content {
  estado?: "candidato_respaldado" | "evidencia_insuficiente";
  estado_motivo?: string | null;
  causas_ocurrencia: Causa[];
  causa_no_deteccion: Causa | null;
  descartes?: { codigo: string; motivo: string }[];
  indice_fuentes: Record<string, FuenteRef>;
}

export type D2Content = Record<"que" | "por_que" | "donde" | "cuando" | "quien" | "como" | "cuanto", Hecho> & {
  indice_fuentes: Record<string, FuenteRef>;
};

export interface Section {
  discipline: "D2" | "D3" | "D4";
  version_no: number;
  kind: "agente" | "edicion" | "aprobacion" | "rechazo";
  content: Record<string, unknown> | null;
  feedback: string | null;
  author: string | null;
  created_at: string;
}

export interface Run {
  run_id: string;
  status: "en_curso" | "completada" | "parcial" | "sin_borrador" | "fallida" | "abandonada";
  disciplines: string[];
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  stage_ms: Record<string, number>;
  usage: Record<string, number | null>;
  blocked: Record<string, string>;
  written: Record<string, unknown>;
  error: string | null;
  config_id: string | null;
}

export interface AuditEntry {
  id: number;
  created_at: string;
  trace_id: string | null;
  stage: string;
  detected_level: string;
  destination: "local" | "api";
  provider: string;
  model: string;
  tier: string | null;
  simulated: boolean;
  fragments: number;
  redaction_applied: boolean;
  pseudonymized: boolean;
  redactions: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  cost_usd: number | null;
  latency_ms: number | null;
  outcome: string | null;
  error: string | null;
  finish_reason: string | null;
  hash: string;
}

export interface Audit {
  chain_ok: boolean;
  chain_checked: number;
  head_hash: string | null;
  entries: AuditEntry[];
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    credentials: "same-origin",
    headers: {
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...(init.headers ?? {}),
    },
  });
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const data = text ? safeJson(text) : null;
  if (!res.ok) {
    throw new ApiError(res.status, detailOf(data) ?? `Error ${res.status}`);
  }
  return data as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function detailOf(data: unknown): string | null {
  if (data && typeof data === "object" && "detail" in data) {
    const d = (data as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((x) => (x as { msg?: string }).msg ?? String(x)).join("; ");
  }
  return typeof data === "string" && data.length < 300 ? data : null;
}

const post = <T>(path: string, body?: unknown, headers?: Record<string, string>) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body), headers });

export const api = {
  demoUsers: () => request<User[]>("/auth/demo-users"),
  login: (username: string) => post<User>("/auth/demo-login", { username }),
  logout: () => post<void>("/auth/logout"),
  me: () => request<User>("/auth/me"),

  ncrs: () => request<Ncr[]>("/ncrs?limit=100"),
  ncr: (id: string) => request<Ncr>(`/ncrs/${id}`),
  openNcr: (body: {
    plant_id: string;
    line_id: string;
    shift: number;
    description: string;
    part_number?: string;
    customer_id?: string;
  }) => post<Ncr>("/ncrs", body),

  sections: (id: string) => request<Section[]>(`/ncrs/${id}/sections`),
  edit: (id: string, d: string, based_on_version: number, content: unknown) =>
    post<Section>(`/ncrs/${id}/sections/${d}/edit`, { based_on_version, content }),
  reject: (id: string, d: string, based_on_version: number, feedback: string, reason?: string) =>
    post<Section>(`/ncrs/${id}/sections/${d}/reject`, {
      based_on_version,
      feedback,
      ...(reason ? { reason } : {}),
    }),
  approve: (id: string, d: string, based_on_version: number) =>
    post<Section>(`/ncrs/${id}/sections/${d}/approve`, { based_on_version }),

  analyze: (id: string, key: string) =>
    post<unknown>(`/ncrs/${id}/analyze`, undefined, { "Idempotency-Key": key }),
  runs: (id: string) => request<Run[]>(`/ncrs/${id}/runs`),
  audit: (id: string) => request<Audit>(`/ncrs/${id}/audit`),
};

export const ROLE_LABEL: Record<Role, string> = {
  inspector: "Inspector",
  ingeniero: "Ingeniero de calidad",
  gerente: "Gerente de calidad",
  auditor: "Auditor",
};

export const STATUS_LABEL: Record<string, string> = {
  abierta: "Abierta",
  en_analisis: "En análisis",
  pendiente_aprobacion: "Pendiente de aprobación",
  aprobada: "Aprobada",
};

export const REJECT_REASONS: { value: string; label: string }[] = [
  { value: "causa_incorrecta", label: "La causa principal no es la causa" },
  { value: "evidencia_insuficiente", label: "Lo citado no sostiene la causa" },
  { value: "cita_irrelevante", label: "Cita fuentes que no hablan del caso" },
  { value: "contexto_incompleto", label: "Faltó un dato disponible" },
  { value: "redaccion", label: "Contenido correcto, mal expresado" },
  { value: "error_tecnico", label: "Formato roto o campos raros" },
];

export function scopeLabel(u: User): string {
  return u.scopes.map((s) => (s.line_id ? `${s.plant_id} · ${s.line_id}` : `${s.plant_id} · planta`)).join(", ");
}

export function fmtDate(iso: string): string {
  return new Date(iso).toLocaleString("es-MX", { dateStyle: "medium", timeStyle: "short" });
}
