import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useT } from "../i18n/context";
import type { AgentEvent, ContaminationMetrics, ReplaySession, TraceSummary } from "../types";

export function ReplayAnalyzer() {
  const { t } = useT();
  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);
  const [session, setSession] = useState<ReplaySession | null>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [currentEvent, setCurrentEvent] = useState<AgentEvent | null>(null);
  const [speed, setSpeed] = useState(1);
  const [contamination, setContamination] = useState<ContaminationMetrics | null>(null);

  const loadTraces = useCallback(async () => {
    try {
      const list = await api.listTraces();
      setTraces(list);
    } catch { /* offline */ }
  }, []);

  useEffect(() => { loadTraces(); }, [loadTraces]);

  const startReplay = useCallback(async (traceId: string) => {
    setSelectedTraceId(traceId);
    setContamination(null);
    try {
      const result = await api.startReplay(traceId);
      setSession(result as unknown as ReplaySession);
      const allEvents = await api.getTrace(traceId);
      setEvents(allEvents);
      const cMetrics = await api.getContaminationMetrics(traceId);
      setContamination(cMetrics);
    } catch { /* ignore */ }
  }, []);

  const stepForward = useCallback(async () => {
    if (!session) return;
    try {
      const result = await api.stepReplay(session.session_id);
      if (result.event) setCurrentEvent(result.event as unknown as AgentEvent);
      setSession(result as unknown as ReplaySession);
    } catch { /* ignore */ }
  }, [session]);

  const seekTo = useCallback(async (index: number) => {
    if (!session) return;
    try {
      const updated = await api.seekReplay(session.session_id, index);
      setSession(updated as unknown as ReplaySession);
      setCurrentEvent(events[index] ?? null);
    } catch { /* ignore */ }
  }, [session, events]);

  const playPause = useCallback(async () => {
    if (!session) return;
    const isPlaying = session.state === "playing";
    try {
      const updated = isPlaying
        ? await api.pauseReplay(session.session_id)
        : await api.resumeReplay(session.session_id);
      setSession(updated as unknown as ReplaySession);
    } catch { /* ignore */ }
  }, [session]);

  return (
    <div className="grid h-screen grid-cols-[320px_minmax(0,1fr)] bg-slate-100 text-slate-950">
      <aside className="flex flex-col border-r border-slate-200 bg-white">
        <div className="border-b border-slate-200 px-5 py-4">
          <h2 className="text-base font-semibold">{t("replay.title")}</h2>
          <p className="mt-1 text-xs text-slate-500">{t("replay.subtitle")}</p>
        </div>
        <div className="min-h-0 flex-1 space-y-1 overflow-y-auto p-3">
          {traces.map((tr) => (
            <button
              key={tr.trace_id}
              className={`w-full rounded-lg border px-3 py-2.5 text-left text-xs transition hover:border-teal-400 ${
                selectedTraceId === tr.trace_id ? "border-teal-500 bg-teal-50" : "border-slate-200 bg-slate-50"
              }`}
              onClick={() => startReplay(tr.trace_id)}
            >
              <div className="font-semibold text-slate-900 truncate">{tr.trace_id}</div>
              <div className="mt-1 flex items-center gap-2 text-slate-500">
                <span>{tr.event_count} {t("replay.events")}</span>
                <span>·</span>
                <span>{tr.nodes_involved?.length ?? 0} {t("replay.nodes")}</span>
              </div>
            </button>
          ))}
        </div>
      </aside>

      <section className="flex min-h-0 flex-col">
        {selectedTraceId ? (
          <div className="flex min-h-0 flex-1 flex-col">
            <div className="flex items-center gap-3 border-b border-slate-200 bg-white px-6 py-3">
              <button className="rounded border px-3 py-1.5 text-xs font-semibold hover:bg-slate-100" onClick={stepForward}>
                {t("replay.step")} ▶
              </button>
              <button className="rounded border px-3 py-1.5 text-xs font-semibold hover:bg-slate-100" onClick={playPause}>
                {session?.state === "playing" ? `${t("replay.pause")} ⏸` : `${t("replay.play")} ▶`}
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
                onChange={async (e) => {
                  const v = Number(e.target.value);
                  setSpeed(v);
                  if (session) {
                    const updated = await api.speedReplay(session.session_id, v);
                    setSession(updated as unknown as ReplaySession);
                  }
                }}
              >
                {[0.5, 1, 2, 4, 8].map((s) => (
                  <option key={s} value={s}>{s}x</option>
                ))}
              </select>
              <span className="ml-auto text-xs text-slate-500">
                {session?.state ?? t("replay.idle")}
              </span>
            </div>

            {/* Contamination Summary */}
            {contamination && (
              <div className="border-b border-slate-200 bg-white px-6 py-3">
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Contamination Summary
                </h3>
                <div className="grid grid-cols-4 gap-3 text-xs">
                  <div className="rounded border border-slate-200 bg-slate-50 p-2">
                    <div className="text-slate-500">Propagation Depth</div>
                    <div className="text-lg font-bold text-slate-900">{contamination.propagation_depth}</div>
                  </div>
                  <div className="rounded border border-slate-200 bg-slate-50 p-2">
                    <div className="text-slate-500">Blast Radius</div>
                    <div className="text-lg font-bold text-slate-900">{contamination.blast_radius}</div>
                  </div>
                  <div className="rounded border border-slate-200 bg-slate-50 p-2">
                    <div className="text-slate-500">Max Score</div>
                    <div className={`text-lg font-bold ${contamination.max_contamination_score > 0.5 ? "text-rose-600" : "text-slate-900"}`}>
                      {contamination.max_contamination_score.toFixed(2)}
                    </div>
                  </div>
                  <div className="rounded border border-slate-200 bg-slate-50 p-2">
                    <div className="text-slate-500">Time to Detection</div>
                    <div className="text-lg font-bold text-slate-900">
                      {contamination.time_to_detection_ms != null ? `${contamination.time_to_detection_ms.toFixed(0)}ms` : "N/A"}
                    </div>
                  </div>
                  <div className="rounded border border-slate-200 bg-slate-50 p-2">
                    <div className="text-slate-500">Recovery</div>
                    <div className={`text-lg font-bold ${contamination.recovery_success ? "text-emerald-600" : "text-rose-600"}`}>
                      {contamination.recovery_success ? "Yes" : "No"}
                    </div>
                  </div>
                  <div className="rounded border border-slate-200 bg-slate-50 p-2">
                    <div className="text-slate-500">Persistence</div>
                    <div className={`text-lg font-bold ${contamination.contamination_persistence > 0.3 ? "text-amber-600" : "text-slate-900"}`}>
                      {(contamination.contamination_persistence * 100).toFixed(0)}%
                    </div>
                  </div>
                  <div className="rounded border border-slate-200 bg-slate-50 p-2">
                    <div className="text-slate-500">Contaminated Nodes</div>
                    <div className="text-xs font-medium text-slate-700 truncate" title={contamination.contaminated_nodes.join(", ")}>
                      {contamination.contaminated_nodes.length > 0 ? contamination.contaminated_nodes.join(", ") : "None"}
                    </div>
                  </div>
                </div>
              </div>
            )}

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
                          {t("replay.meta")}: {JSON.stringify(evt.metadata).slice(0, 120)}
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
            {t("replay.select")}
          </div>
        )}
      </section>
    </div>
  );
}
