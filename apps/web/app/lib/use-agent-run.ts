import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api, errorText, type Run } from "./api";
import { invalidateNcr, keys, POLL_MS, useAnalyze } from "./queries";

const GIVE_UP_MS = 15 * 60 * 1000;
const CLOCK_SKEW_MS = 10_000;

/**
 * Estado de la corrida que se sigue. `startedAt` es el momento en que este navegador la lanzó;
 * sin él, se sigue la que el servidor reporta en curso (p. ej. al volver a la página).
 */
export function runState(runs: Run[] | undefined, startedAt: number | null, now: number) {
  const list = runs ?? [];
  const active = list.find((r) => r.status === "en_curso" && now - Date.parse(r.started_at) < GIVE_UP_MS);
  const since = startedAt ?? (active ? Date.parse(active.started_at) : null);
  const followed = since === null ? undefined : list.find((r) => Date.parse(r.started_at) >= since - CLOCK_SKEW_MS);
  const finished = followed && followed.status !== "en_curso" ? followed : undefined;
  const expired = since !== null && now - since > GIVE_UP_MS;
  return { since, finished, expired, running: since !== null && !finished && !expired };
}

export function useAgentRun(ncrId: string) {
  const qc = useQueryClient();
  const analyze = useAnalyze(ncrId);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [last, setLast] = useState<Run | null>(null);
  const [timedOut, setTimedOut] = useState(false);

  const runsQuery = useQuery({
    queryKey: keys.runs(ncrId),
    queryFn: () => api.runs(ncrId),
    refetchInterval: (query) => (runState(query.state.data, startedAt, Date.now()).running ? POLL_MS : false),
  });
  const state = runState(runsQuery.data, startedAt, now);

  useEffect(() => {
    if (!state.running) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [state.running]);

  const wasRunning = useRef(false);
  useEffect(() => {
    if (wasRunning.current && !state.running) {
      const runs = runsQuery.data ?? [];
      setLast(state.finished ?? runs.reduce<Run | null>((a, r) => (!a || r.started_at > a.started_at ? r : a), null));
      setTimedOut(state.expired);
      setStartedAt(null);
      void invalidateNcr(qc, ncrId);
    }
    wasRunning.current = state.running;
  }, [state.running, state.finished, state.expired, runsQuery.data, qc, ncrId]);

  function start(agentInstructions: string) {
    const since = Date.now();
    setLast(null);
    setTimedOut(false);
    setNow(since);
    setStartedAt(since);
    analyze.mutate(agentInstructions, { onError: () => setStartedAt(null) });
  }

  return {
    runs: runsQuery.data,
    runsError: runsQuery.error,
    running: state.running,
    elapsedMs: state.since === null ? 0 : Math.max(0, now - state.since),
    last,
    error: analyze.error
      ? errorText(analyze.error)
      : timedOut
        ? "La corrida no terminó en 15 minutos; revisa la pestaña Corridas."
        : null,
    start,
  };
}

export type AgentRun = ReturnType<typeof useAgentRun>;
