import { useMutation, useQuery } from "@tanstack/react-query";
import { Pause, Play, RotateCcw, SkipForward } from "lucide-react";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../lib/api";
import type { ReplaySession } from "../lib/types";
import { getErrorMessage } from "../lib/utils";
import { useAppStore } from "../store/app-store";
import { JsonViewer } from "../components/common/JsonViewer";
import { StatusBadge } from "../components/common/StatusBadge";

export function Replay() {
  const params = useParams();
  const addToast = useAppStore((state) => state.addToast);
  const [traceId, setTraceId] = useState(params.traceId ?? "");
  const [session, setSession] = useState<ReplaySession | null>(null);
  const traces = useQuery({ queryKey: ["traces"], queryFn: api.listTraces });
  useEffect(() => {
    if (!traceId && traces.data?.length) setTraceId(traces.data[0].trace_id);
  }, [traceId, traces.data]);

  const action = useMutation({
    mutationFn: async (type: string) => {
      if (type === "start") return api.startReplay(traceId);
      if (!session) throw new Error("请先启动回放");
      if (type === "pause") return api.pauseReplay(session.session_id);
      if (type === "resume") return api.resumeReplay(session.session_id);
      if (type === "step") return api.stepReplay(session.session_id);
      throw new Error("未知回放操作");
    },
    onSuccess: setSession,
    onError: (error) => addToast(getErrorMessage(error), "error"),
  });

  const seek = useMutation({
    mutationFn: (position: number) => api.seekReplay(session!.session_id, position),
    onSuccess: setSession,
  });
  const speed = useMutation({
    mutationFn: (multiplier: number) =>
      api.speedReplay(session!.session_id, multiplier),
    onSuccess: setSession,
  });
  const events = useQuery({
    queryKey: ["trace", traceId],
    queryFn: () => api.getTrace(traceId),
    enabled: Boolean(traceId),
  });
  const currentEvent = session?.event ?? events.data?.[session?.current_index ?? 0];

  return (
    <div className="space-y-4 p-5">
      <div>
        <h2 className="text-xl font-semibold text-white">事件回放</h2>
        <p className="mt-1 text-xs text-slate-500">
          按游标重放 Trace，逐步检查污染传播和防御动作。
        </p>
      </div>
      <section className="panel overflow-hidden">
        <div className="flex flex-wrap items-center gap-3 border-b border-slate-800 p-4">
          <select
            className="input max-w-xl font-mono"
            value={traceId}
            onChange={(event) => {
              setTraceId(event.target.value);
              setSession(null);
            }}
          >
            {(traces.data ?? []).map((trace) => (
              <option key={trace.trace_id} value={trace.trace_id}>
                {trace.trace_id}
              </option>
            ))}
          </select>
          <button type="button" className="btn-primary" onClick={() => action.mutate("start")} disabled={!traceId}>
            <RotateCcw className="size-4" />
            启动回放
          </button>
          {session && <StatusBadge status={session.state} />}
        </div>

        <div className="flex flex-wrap items-center gap-3 border-b border-slate-800 p-4">
          <button
            type="button"
            className="btn"
            disabled={!session}
            onClick={() => action.mutate(session?.state === "playing" ? "pause" : "resume")}
          >
            {session?.state === "playing" ? <Pause className="size-4" /> : <Play className="size-4" />}
            {session?.state === "playing" ? "暂停" : "播放"}
          </button>
          <button type="button" className="btn" disabled={!session} onClick={() => action.mutate("step")}>
            <SkipForward className="size-4" />
            单步
          </button>
          <input
            type="range"
            min={0}
            max={Math.max(0, (session?.total_events ?? 1) - 1)}
            value={session?.current_index ?? 0}
            disabled={!session}
            onChange={(event) => seek.mutate(Number(event.target.value))}
            className="min-w-64 flex-1 accent-cyan-400"
          />
          <span className="w-24 text-center font-mono text-xs text-slate-400">
            {(session?.current_index ?? 0) + 1} / {session?.total_events ?? 0}
          </span>
          <select
            className="input w-24"
            value={session?.speed_multiplier ?? 1}
            disabled={!session}
            onChange={(event) => speed.mutate(Number(event.target.value))}
          >
            {[0.25, 0.5, 1, 2, 4, 6].map((value) => (
              <option key={value} value={value}>{value}x</option>
            ))}
          </select>
        </div>

        <div className="grid min-h-[520px] lg:grid-cols-[minmax(0,1fr)_420px]">
          <div className="border-r border-slate-800 p-5">
            <div className="relative h-full min-h-[420px] overflow-hidden rounded-xl border border-slate-700 bg-[#04101a]">
              <div className="absolute inset-x-10 top-1/2 h-px bg-slate-700" />
              {(events.data ?? []).map((event, index) => {
                const percent =
                  ((index + 1) / Math.max(events.data?.length ?? 1, 1)) * 86 + 7;
                const active = index === (session?.current_index ?? 0);
                return (
                  <button
                    type="button"
                    key={event.event_id}
                    onClick={() => session && seek.mutate(index)}
                    className={`absolute top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full border transition ${
                      active
                        ? "size-6 border-cyan-300 bg-cyan-450 shadow-glow"
                        : "size-3 border-slate-500 bg-ink-800 hover:border-cyan-400"
                    }`}
                    style={{ left: `${percent}%` }}
                    title={`${event.source_node} → ${event.target_node}`}
                  />
                );
              })}
              <div className="absolute inset-x-0 bottom-16 text-center">
                <div className="text-sm font-semibold text-slate-200">
                  {currentEvent
                    ? `${currentEvent.source_node} → ${currentEvent.target_node}`
                    : "选择 Trace 并启动回放"}
                </div>
                <div className="mx-auto mt-2 max-w-xl px-6 text-xs leading-6 text-slate-500">
                  {currentEvent?.payload_snippet ?? "事件节点会按后端游标状态高亮显示。"}
                </div>
              </div>
            </div>
          </div>
          <div className="p-4">
            <h3 className="section-title mb-3">当前事件详情</h3>
            <JsonViewer value={currentEvent ?? session ?? {}} className="h-[470px]" />
          </div>
        </div>
      </section>
    </div>
  );
}
