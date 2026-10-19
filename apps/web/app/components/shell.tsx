"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { createContext, useContext, useEffect, type ReactNode } from "react";
import { ApiError, ROLE_LABEL, scopeLabel, type User } from "../lib/api";
import { useLogout, useMe } from "../lib/queries";
import { Spinner } from "./ui";

const SessionContext = createContext<User | null>(null);

export function useUser(): User {
  const u = useContext(SessionContext);
  if (!u) throw new Error("useUser fuera de <Shell>");
  return u;
}

/** Exige sesión: sin cookie válida manda a /login. */
export function Shell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { data: user, error } = useMe();
  const logoutMutation = useLogout();

  useEffect(() => {
    if (error) router.replace(error instanceof ApiError && error.status === 401 ? "/login" : "/login?error=api");
  }, [error, router]);

  if (!user) {
    return (
      <div className="flex flex-1 items-center justify-center gap-2 text-sm text-muted">
        <Spinner /> Cargando sesión…
      </div>
    );
  }

  const logout = () => logoutMutation.mutate(undefined, { onSuccess: () => router.replace("/login") });

  return (
    <SessionContext.Provider value={user}>
      <header className="border-b border-border bg-surface">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <Link href="/ncrs" className="flex items-baseline gap-2">
            <span className="text-sm font-semibold tracking-tight">Agente 8D</span>
            <span className="text-xs text-muted">Cablenova Juárez · causa raíz</span>
          </Link>
          <div className="flex items-center gap-3 text-sm">
            <div className="text-right leading-tight">
              <div className="font-medium">{user.display_name}</div>
              <div className="text-xs text-muted">
                {ROLE_LABEL[user.role]} · {scopeLabel(user)}
              </div>
            </div>
            <button onClick={logout} className="text-xs text-muted underline-offset-2 hover:underline">
              Salir
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">{children}</main>
    </SessionContext.Provider>
  );
}
