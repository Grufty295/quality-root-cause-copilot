"use client";

import type { ButtonHTMLAttributes, ReactNode } from "react";

type Tone = "neutral" | "red" | "amber" | "green" | "blue" | "violet";

const TONES: Record<Tone, string> = {
  neutral: "bg-zinc-100 text-zinc-700 ring-zinc-200",
  red: "bg-red-50 text-red-700 ring-red-200",
  amber: "bg-amber-50 text-amber-800 ring-amber-200",
  green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  blue: "bg-sky-50 text-sky-700 ring-sky-200",
  violet: "bg-violet-50 text-violet-700 ring-violet-200",
};

export function Badge({ tone = "neutral", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset whitespace-nowrap ${TONES[tone]}`}
    >
      {children}
    </span>
  );
}

export function levelTone(level: string | null | undefined): Tone {
  if (level === "confidencial") return "red";
  if (level === "interno") return "blue";
  return "neutral";
}

export function LevelBadge({ level }: { level: string | null | undefined }) {
  return <Badge tone={levelTone(level)}>{level ?? "sin clasificar"}</Badge>;
}

export function statusTone(status: string): Tone {
  return (
    ({
      abierta: "neutral",
      en_analisis: "amber",
      pendiente_aprobacion: "blue",
      aprobada: "green",
      completada: "green",
      parcial: "amber",
      sin_borrador: "red",
      fallida: "red",
      abandonada: "neutral",
      en_curso: "violet",
    } as Record<string, Tone>)[status] ?? "neutral"
  );
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" };

export function Button({ variant = "secondary", className = "", ...props }: ButtonProps) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition disabled:opacity-50 disabled:cursor-not-allowed";
  const styles = {
    primary: "bg-zinc-900 text-white hover:bg-zinc-700",
    secondary: "bg-surface text-foreground ring-1 ring-border hover:bg-zinc-50",
    danger: "bg-red-600 text-white hover:bg-red-500",
  }[variant];
  return <button {...props} className={`${base} ${styles} ${className}`} />;
}

export function Card({ title, actions, children }: { title?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-border bg-surface">
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2.5">
          <h2 className="text-sm font-semibold">{title}</h2>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function ErrorBox({ error }: { error: string | null }) {
  if (!error) return null;
  return <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700 ring-1 ring-red-200">{error}</p>;
}

export function Spinner() {
  return (
    <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-r-transparent" />
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="text-sm text-muted">{children}</p>;
}
