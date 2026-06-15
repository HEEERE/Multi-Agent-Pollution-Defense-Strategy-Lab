import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Clock3,
  Network,
  Search,
  ShieldCheck,
  Trash2,
  Waves,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import type { AgentEvent } from "../lib/types";
import {
  compactId,
  formatDuration,
  formatPercent,
  formatTime,
  getErrorMessage,
} from "../lib/utils";
import { useAppStore } from "../store/app-store";
import { JsonViewer } from "../components/common/JsonViewer";
import { Loading } from "../components/common/Loading";
import { MetricCard } from "../components/common/MetricCard";
import { StatusBadge } from "../components/common/StatusBadge";
import { TraceGraph } from "../components/graph/TraceGraph";

export function TraceExplorer() {
  const queryClient = useQueryClient();
  const addToast = useAppStore((state) => state.addToast);
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedTrace = searchParams.get("trace");
  const [selectedId, setSelectedId] = useState<string | null>(requestedTrace);
  const [selectedEvent, setSelectedEvent] = useState<AgentEvent | null>(null);
  const [search, setSearch] = useState("");

  const traces = useQuery({ queryKey: ["traces"], queryFn: api.listTraces });
  useEffect(() => {
    if (requestedTrace) setSelectedId(requestedTrace);
    else if (!selectedId && traces.data?.length) setSelectedId(traces.data[0].trace_id);
  }, [requestedTrace, selectedId, traces.data]);

  const events = useQuery({
    queryKey: ["trace", selectedId],
    queryFn: () => api.getTrace(selectedId!),
    enabled: Boolean(selectedId),
  });
  const graph = useQuery({
    queryKey: ["trace-graph", selectedId],
    queryFn: () => api.getTraceGraph(selectedId!),
    enabled: Boolean(selectedId),
  });
  const contamination = useQuery({
    queryKey: ["trace-contamination", selectedId],
    queryFn: () => api.getTraceContamination(selectedId!),
    enabled: Boolean(selectedId),
  });
  const remove = useMutation({
    mutationFn: () => api.deleteTrace(selectedId!),
    onSuccess: async () => {
      setSelectedId(null);
      setSearchParams({});
      await queryClient.invalidateQueries({ queryKey: ["traces"] });
      addToast("Trace 已删除", "success");
    },
    onError: (error) => addToast(getErrorMessage(error), "error"),
  });

  useEffect(() => {
    setSelectedEvent(events.data?.[0] ?? null);
  }, [events.data]);

  const filtered = useMemo(
    () =>
      (traces.data ?? []).filter((trace) =>
        trace.trace_id.toLowerCase().includes(search.toLowerCase()),
      ),
    [search, traces.data],
  );

  return (
    <div className="grid h-full min-h-0 grid-cols-[190px_minmax(0,1fr)_290px] overflow-hidden xl:grid-cols-[215px_minmax(0,1fr)_330px] min-[1360px]:grid-cols-[245px_minmax(560px,1fr)_360px]">
      <aside className="flex min-h-0 flex-col border-r border-slate-800 bg-[#07141f]">
        <div className="panel-header">
          <h2 className="section-title">追踪列表</h2>
          <span className="muted">{traces.data?.length ?? 0}</span>
        </div>
        <div className="p-3">
          <label className="relative">
            <Search className="absolute left-3 top-3 size-4 text-slate-500" />
            <input
              className="input pl-9"
              placeholder="搜索 trace_id"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
        </div>
        <div className="min-h-0 flex-1 space-y-2 overflow-auto px-2 pb-3">
          {filtered.map((trace) => {
            const hasCritical =
              (trace.status_counts.infected ?? 0) +
                (trace.severity_counts.critical ?? 0) >
              0;
            return (
              <button
                type="button"
                key={trace.trace_id}
                onClick={() => {
                  setSelectedId(trace.trace_id);
                  setSearchParams({ trace: trace.trace_id });
                }}
                className={`w-full rounded-lg border p-3 text-left ${
                  selectedId === trace.trace_id
                    ? "border-cyan-450 bg-cyan-450/10"
                    : "border-slate-800 bg-ink-900 hover:border-slate-600"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate font-mono text-xs text-slate-200">
                    {compactId(trace.trace_id, 24)}
                  </span>
                  <StatusBadge status={hasCritical ? "infected" : "safe"} />
                </div>
                <div className="mt-2 flex justify-between text-[10px] text-slate-500">
                  <span>{formatTime(trace.start_time)}</span>
                  <span>{trace.event_count} 个事件</span>
                </div>
              </button>
            );
          })}
        </div>
      </aside>

      <section className="flex min-h-0 flex-col bg-ink-950 p-3">
        <div className="mb-3 flex h-10 items-center justify-between">
          <div className="min-w-0">
            <h2 className="truncate font-mono text-sm font-semibold text-white">
              {selectedId ?? "请选择 Trace"}
            </h2>
            <p className="mt-1 text-[10px] text-slate-500">
              节点颜色与污染分数来自后端 TraceGraph
            </p>
          </div>
          {selectedId && (
            <button
              type="button"
              className="btn-danger h-8"
              onClick={() => window.confirm("确定删除这个 Trace？") && remove.mutate()}
            >
              <Trash2 className="size-3.5" />
              删除
            </button>
          )}
        </div>
        <div className="min-h-0 flex-1">
          {graph.isLoading ? (
            <div className="panel h-full"><Loading label="正在重建传播图" /></div>
          ) : (
            <TraceGraph
              graph={graph.data}
              events={events.data}
              onNodeClick={(nodeId) => {
                const event = events.data?.find(
                  (item) => item.source_node === nodeId || item.target_node === nodeId,
                );
                if (event) setSelectedEvent(event);
              }}
            />
          )}
        </div>
        <div className="mt-3 flex min-h-24 gap-2 overflow-x-auto rounded-xl border border-slate-800 bg-[#07141f] p-3">
          {(events.data ?? []).map((event) => (
            <button
              type="button"
              key={event.event_id}
              onClick={() => setSelectedEvent(event)}
              className={`min-w-36 rounded-lg border px-3 py-2 text-left ${
                selectedEvent?.event_id === event.event_id
                  ? "border-cyan-450 bg-cyan-450/10"
                  : "border-slate-700 bg-ink-900"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="font-mono text-[10px] text-slate-500">
                  {formatTime(event.timestamp)}
                </span>
                <span
                  className={`size-2 rounded-full ${
                    event.status === "infected"
                      ? "bg-red-400"
                      : event.status === "quarantined"
                        ? "bg-violet-400"
                        : "bg-emerald-400"
                  }`}
                />
              </div>
              <div className="mt-2 truncate text-xs text-slate-300">
                {event.source_node} → {event.target_node}
              </div>
            </button>
          ))}
        </div>
      </section>

      <aside className="min-h-0 overflow-auto border-l border-slate-800 bg-[#07141f]">
        <div className="panel-header">
          <h3 className="section-title">污染分析</h3>
          <Waves className="size-4 text-cyan-350" />
        </div>
        <div className="grid grid-cols-2 gap-3 p-3">
          <MetricCard
            label="传播深度"
            value={contamination.data?.propagation_depth ?? "--"}
            icon={Network}
            tone="red"
          />
          <MetricCard
            label="爆炸半径"
            value={contamination.data?.blast_radius ?? "--"}
            icon={Waves}
            tone="amber"
          />
          <MetricCard
            label="检测耗时"
            value={formatDuration(contamination.data?.time_to_detection_ms)}
            icon={Clock3}
            tone="cyan"
          />
          <MetricCard
            label="恢复成功"
            value={contamination.data?.recovery_success ? "是" : "否"}
            icon={ShieldCheck}
            tone={contamination.data?.recovery_success ? "green" : "violet"}
          />
        </div>
        <div className="space-y-3 border-y border-slate-800 p-4">
          <div className="flex justify-between text-xs">
            <span className="text-slate-500">最大污染分数</span>
            <span className="font-mono text-red-300">
              {contamination.data?.max_contamination_score?.toFixed(2) ?? "--"}
            </span>
          </div>
          <div className="flex justify-between text-xs">
            <span className="text-slate-500">污染持续性</span>
            <span className="font-mono text-amber-300">
              {formatPercent(contamination.data?.contamination_persistence)}
            </span>
          </div>
        </div>
        <div className="panel-header">
          <h3 className="section-title">当前事件 JSON</h3>
        </div>
        <JsonViewer value={selectedEvent ?? {}} className="p-3" />
      </aside>
    </div>
  );
}
