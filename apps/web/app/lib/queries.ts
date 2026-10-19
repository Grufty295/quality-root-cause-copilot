import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api, ApiError } from "./api";

export const POLL_MS = 4000;

export const keys = {
  me: ["me"] as const,
  demoUsers: ["demo-users"] as const,
  ncrs: ["ncrs"] as const,
  ncr: (id: string) => ["ncr", id] as const,
  sections: (id: string) => ["ncr", id, "sections"] as const,
  runs: (id: string) => ["ncr", id, "runs"] as const,
  audit: (id: string) => ["ncr", id, "audit"] as const,
};

export const useMe = () => useQuery({ queryKey: keys.me, queryFn: api.me, retry: false, staleTime: Infinity });
export const useDemoUsers = () => useQuery({ queryKey: keys.demoUsers, queryFn: api.demoUsers });
export const useNcrs = () => useQuery({ queryKey: keys.ncrs, queryFn: api.ncrs });
export const useNcr = (id: string) => useQuery({ queryKey: keys.ncr(id), queryFn: () => api.ncr(id) });
export const useSections = (id: string) => useQuery({ queryKey: keys.sections(id), queryFn: () => api.sections(id) });
export const useAudit = (id: string) => useQuery({ queryKey: keys.audit(id), queryFn: () => api.audit(id) });

/** Las corridas se consultan cada `POLL_MS` solo mientras el agente trabaja. */
export const useRuns = (id: string, polling: boolean) =>
  useQuery({
    queryKey: keys.runs(id),
    queryFn: () => api.runs(id),
    refetchInterval: polling ? POLL_MS : false,
  });

/** Todo lo que depende de la NCR (secciones, corridas, auditoría) y la lista, que muestra su estado. */
export function invalidateNcr(qc: QueryClient, id: string) {
  return Promise.all([
    qc.invalidateQueries({ queryKey: keys.ncr(id) }),
    qc.invalidateQueries({ queryKey: keys.ncrs }),
  ]);
}

export function useOpenNcr() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.openNcr,
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.ncrs }),
  });
}

type Review = { discipline: string; version: number };

export function useEditSection(ncrId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ discipline, version, content }: Review & { content: unknown }) =>
      api.edit(ncrId, discipline, version, content),
    onSuccess: () => invalidateNcr(qc, ncrId),
  });
}

export function useRejectSection(ncrId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ discipline, version, feedback, reason }: Review & { feedback: string; reason?: string }) =>
      api.reject(ncrId, discipline, version, feedback, reason),
    onSuccess: () => invalidateNcr(qc, ncrId),
  });
}

export function useApproveSection(ncrId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ discipline, version }: Review) => api.approve(ncrId, discipline, version),
    onSuccess: () => invalidateNcr(qc, ncrId),
  });
}

/** El proxy (502/504) corta las peticiones largas, pero la corrida sigue: `useRuns` la recoge. */
export function useAnalyze(ncrId: string) {
  return useMutation({
    mutationFn: (agentInstructions: string) =>
      api.analyze(ncrId, agentInstructions.trim() || undefined).catch((e) => {
        if (!(e instanceof ApiError && (e.status === 502 || e.status === 504))) throw e;
      }),
  });
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.login,
    onSuccess: () => qc.resetQueries(),
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.logout().catch(() => undefined),
    onSuccess: () => qc.clear(),
  });
}
