"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { errorText, ROLE_LABEL, scopeLabel, type Role } from "../lib/api";
import { useDemoUsers, useLogin } from "../lib/queries";
import { ErrorBox, Spinner } from "../components/ui";

const ROLE_HINT: Record<Role, string> = {
  inspector: "Abre NCR y ve los borradores en solo lectura",
  ingeniero: "Corre el agente, edita y puede rechazar",
  gerente: "Aprueba o rechaza las secciones",
  auditor: "Revisa corridas y el log de auditoría",
};

const ORDER: Role[] = ["inspector", "ingeniero", "gerente", "auditor"];

export default function LoginPage() {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const demoUsers = useDemoUsers();
  const login = useLogin();
  const users = demoUsers.data;
  const error = login.error
    ? errorText(login.error)
    : demoUsers.error
      ? `No se pudo contactar la API: ${errorText(demoUsers.error)}`
      : null;

  function enter(username: string) {
    setBusy(username);
    login.mutate(username, {
      onSuccess: () => router.replace("/ncrs"),
      onError: () => setBusy(null),
    });
  }

  return (
    <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-12">
      <h1 className="text-xl font-semibold tracking-tight">Agente 8D · Causa raíz</h1>
      <p className="mt-1 text-sm text-muted">
        Demo con datos sintéticos de la planta Cablenova Juárez. Elige un usuario: quien redacta no aprueba, y
        cada rol ve solo su alcance.
      </p>
      <div className="mt-6">
        <ErrorBox error={error} />
      </div>
      {!users && !error && (
        <p className="mt-6 flex items-center gap-2 text-sm text-muted">
          <Spinner /> Cargando usuarios…
        </p>
      )}
      <div className="mt-6 grid gap-6">
        {ORDER.map((role) => {
          const group = (users ?? []).filter((u) => u.role === role);
          if (!group.length) return null;
          return (
            <section key={role}>
              <h2 className="text-sm font-semibold">{ROLE_LABEL[role]}</h2>
              <p className="text-xs text-muted">{ROLE_HINT[role]}</p>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                {group.map((u) => (
                  <button
                    key={u.username}
                    onClick={() => enter(u.username)}
                    disabled={busy !== null}
                    className="rounded-lg border border-border bg-surface px-3 py-2.5 text-left transition hover:border-zinc-400 disabled:opacity-60"
                  >
                    <div className="flex items-center justify-between gap-2 text-sm font-medium">
                      {u.display_name}
                      {busy === u.username && <Spinner />}
                    </div>
                    <div className="text-xs text-muted">
                      {u.username} · {scopeLabel(u)}
                    </div>
                  </button>
                ))}
              </div>
            </section>
          );
        })}
      </div>
    </main>
  );
}
