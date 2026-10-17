"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, ROLE_LABEL, scopeLabel, type Role, type User } from "../lib/api";
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
  const [users, setUsers] = useState<User[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    api
      .demoUsers()
      .then(setUsers)
      .catch((e) => setError(`No se pudo contactar la API: ${e.message}`));
  }, []);

  async function enter(username: string) {
    setBusy(username);
    setError(null);
    try {
      await api.login(username);
      router.replace("/ncrs");
    } catch (e) {
      setError((e as Error).message);
      setBusy(null);
    }
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
