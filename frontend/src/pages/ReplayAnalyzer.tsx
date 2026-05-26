import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { AgentEvent, ReplaySession, TraceSummary } from "../types";

export function ReplayAnalyzer() {
  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);
  const [session, setSession] = useState<ReplaySession | null>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [currentEvent, setCurrentEvent] = useState<AgentEvent | null>(null);
  const [speed, setSpeed] = useState(1);

  const loadTraces = useCallback(async () => {
    try {
      const list = await api.listTraces();
      setTraces(list);
    } catch { /* offline */ }
  }, []);

  useEffect(() => { loadTraces(); }, [loadTraces]);

  const startReplay = useCallback(async (traceId: string) => {
    setSelectedTraceId(traceId);
    try {
      const result = await api.startReplay(traceId);
      setSession({ ...result, trace_id: traceId, speed_multiplier: 1, current_index: 0 } as unknown as ReplaySession);
      const allEvents = await api.getTrace(traceId);
      setEvents(allEvents);
    } catch { /* ignore */ }
  }, []);

  const stepForward = useCallback(async () => {
    if (!session) return;
    try {
      const result = await api.stepReplay(session.session_id);
      if (result.event) setCurrentEvent(result.event as unknown as AgentEvent);
      setSession((prev) => prev ? { ...prev, current_index: result.current_index as number, state: result.state as ReplaySession["state"] } : null);
    } catch { /* ignore */ }
  }, [session]);

  const seekTo = useCallback(async (index: number) => {
    if (!session) return;
    try {
      await api.seekReplay(session.session_id, index);
      setSession((prev) => prev ? { ...prev, current_index: index } : null);
    } catch { /* ignore */ }
  }, [session]);

  const playPause = useCallback(async () => {
    if (!session) return;
    const isPlaying = session.state === "playing";
    try {
      if (isPlaying) await api.pauseReplay(session.session_id);
      else await api.resumeReplay(session.session_id);
      setSession((prev) => prev ? { ...prev, state: isPlaying ? "paused" : "playing" } : null);
    } catch { /* ignore */ }
  }, [session]);

  return (
    <div className="grid h-screen grid-cols-[320px_minmax(0,1fr)] bg-slate-100 text-slate-950">
      <aside className="flex flex-col border-r border-slate-200 bg-white">
        <div className="border-b border-slate-200 px-5 py-4">
          <h2 className="text-base font-semibold">Replay Analyzer</h2>
          <p className="mt-1 text-xs text-slate-500">Step-through trace analysis</p>
        </div>
        <div className="min-h-0 flex-1 space-y-1 overflow-y-auto p-3">
          {traces.map((t) => (
            <button
              key={t.trace_id}
              className={`w-full rounded-lg border px-3 py-2.5 text-left text-xs transition hover:border-teal-400 ${
                selectedTraceId === t.trace_id ? "border-teal-500 bg-teal-50" : "border-slate-200 bg-slate-50"
              }`}
              onClick={() => startReplay(t.trace_id)}
            >
              <div className="font-semibold text-slate-900 truncate">{t.trace_id}</div>
              <div className="mt-1 flex items-center gap-2 text-slate-500">
                <span>{t.event_count} events</span>
                <span>·</span>
                <span>{t.nodes_involved?.length ?? 0} nodes</span>
              </div>
            </button>
          ))}
        </div>
      </aside>

      <section className="flex min-h-0 flex-col">
        {selectedTraceId ? (
          <div className="flex min-h-0 flex-1 flex-col">
            {/* Replay controls */}
            <div className="flex items-center gap-3 border-b border-slate-200 bg-white px-6 py-3">
              <button className="rounded border px-3 py-1.5 text-xs font-semibold hover:bg-slate-100" onClick={stepForward}>
                Step ▶
              </button>
              <button className="rounded border px-3 py-1.5 text-xs font-semibold hover:bg-slate-100" onClick={playPause}>
                {session?.state === "playing" ? "Pause ⏸" : "Play ▶"}
              </button>
              <input
                type="range"
                className="w-32"
                min={0}
                max={events.length - 1}
                value={session?.current_index ?? 0}
                onChange={(e) => seekTo(Number(e.target.value))}
              />
              <span className="text-xs text-slate-500">
                {session?.current_index ?? 0} / {events.length}
              </span>
              <select
                className="rounded border px-2 py-1 text-xs"
                value={speed}
                onChange={(e) => {
                  const v = Number(e.target.value);
                  setSpeed(v);
                  if (session) api.speedReplay(session.session_id, v);
                }}
              >
                {[0.5, 1, 2, 4, 8].map((s) => (
                  <option key={s} value={s}>{s}x</option>
                ))}
              </select>
              <span className="ml-auto text-xs text-slate-500">
                {session?.state ?? "idle"}
              </span>
            </div>

            {/* Event timeline */}
            <div className="min-h-0 flex-1 overflow-y-auto p-4">
              <div className="space-y-1">
                {events.map((evt, i) => (
                  <div
                    key={evt.event_id ?? i}
                    className={`flex items-start gap-3 rounded border px-3 py-2 text-xs transition cursor-pointer ${
                      i === (session?.current_index ?? -1)
                        ? "border-teal-500 bg-teal-50"
                        : "border-slate-100 bg-slate-50 hover:border-slate-300"
                    }`}
                    onClick={() => seekTo(i)}
                  >
                    <span className={`mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full ${
                      evt.status === "safe" ? "bg-emerald-500" : evt.status === "infected" ? "bg-rose-500" : evt.status === "quarantined" ? "bg-gray-400" : "bg-amber-500"
                    }`} />
                    <div className="min-w-0 flex-1">
                      <span className="font-semibold">{evt.source_node} → {evt.target_node}</span>
                      <span className="ml-2 text-slate-500">{evt.event_type} [{evt.status}]</span>
                      <div className="mt-0.5 text-slate-600 truncate">{evt.payload_snippet}</div>
                      {evt.metadata && Object.keys(evt.metadata).length > 0 && (
                        <div className="mt-1 text-teal-600">
                          meta: {JSON.stringify(evt.metadata).slice(0, 120)}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <div className="flex flex-1 items-center justify-center text-sm text-slate-500">
            Select a trace to replay
          </div>
        )}
      </section>
    </div>
  );
}
