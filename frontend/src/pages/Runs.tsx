import { useMutation, useQuery } from "@tanstack/react-query";
import { Ban, ExternalLink, PlayCircle, Search } from "lucide-react";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../lib/api";
import { formatTime, getErrorMessage } from "../lib/utils";
import { useAppStore } from "../store/app-store";
import { EmptyState } from "../components/common/EmptyState";
import { JsonViewer } from "../components/common/JsonViewer";
import { Loading } from "../components/common/Loading";
import { StatusBadge } from "../components/common/StatusBadge";
import { EventTable } from "../components/events/EventTable";

export function Runs() {
  const params = useParams();
  const navigate = useNavigate();
  const addToast = useAppStore((state) => state.addToast);
  const [draftId, setDraftId] = useState(params.runId ?? "");
  const runId = params.runId;
  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.getRun(runId!),
    enabled: Boolean(runId),
    refetchInterval: runId ? 1_500 : false,
  });
  const events = useQuery({
    queryKey: ["run-events", runId],
    queryFn: () => api.getRunEvents(runId!),
    enabled: Boolean(runId),
    refetchInterval: runId ? 1_500 : false,
  });
  const metrics = useQuery({
    queryKey: ["run-metrics", runId],
    queryFn: () => api.getRunMetrics(runId!),
    enabled:
      Boolean(runId) &&
      ["completed", "failed", "cancelled"].includes(run.data?.status ?? ""),
  });
  const cancel = useMutation({
    mutationFn: () => api.cancelRun(runId!),
    onSuccess: () => {
      addToast("已请求取消运行", "success");
      run.refetch();
    },
    onError: (error) => addToast(getErrorMessage(error), "error"),
  });

  return (
    <div className="space-y-4 p-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-white">运行监控</h2>
          <p className="mt-1 text-xs text-slate-500">
            输入 run_id，查看状态、事件、指标与错误信息。
          </p>
        </div>
        <form
          className="flex w-full max-w-xl gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (draftId.trim()) navigate(`/runs/${draftId.trim()}`);
          }}
        >
          <input
            className="input font-mono"
            value={draftId}
            onChange={(event) => setDraftId(event.target.value)}
            placeholder="输入 run_id"
          />
          <button className="btn-primary shrink-0" type="submit">
            <Search className="size-4" />
            查询
          </button>
        </form>
      </div>

      {!runId && (
        <section className="panel">
          <EmptyState
            icon={PlayCircle}
            title="请选择一次运行"
            description="从策略实验室启动策略后会自动获得 run_id，也可在这里手动查询。"
          />
        </section>
      )}
      {runId && run.isLoading && <section className="panel"><Loading /></section>}
      {runId && run.error && (
        <section className="panel border-red-500/40 p-5 text-sm text-red-300">
          {run.error.message}
        </section>
      )}
      {run.data && (
        <>
          <section className="panel overflow-hidden">
            <div className="panel-header">
              <div className="flex items-center gap-3">
                <h3 className="section-title font-mono">{run.data.run_id}</h3>
                <StatusBadge status={run.data.status} />
              </div>
              <div className="flex gap-2">
                {run.data.trace_id && (
                  <button
                    type="button"
                    className="btn"
                    onClick={() => navigate(`/traces?trace=${run.data.trace_id}`)}
                  >
                    <ExternalLink className="size-4" />
                    查看 Trace
                  </button>
                )}
                {["queued", "running"].includes(run.data.status) && (
                  <button type="button" className="btn-danger" onClick={() => cancel.mutate()}>
                    <Ban className="size-4" />
                    取消运行
                  </button>
                )}
              </div>
            </div>
            <div className="grid gap-px bg-slate-800 sm:grid-cols-2 xl:grid-cols-5">
              {[
                ["strategy_id", run.data.strategy_id ?? "--"],
                ["strategy_version", run.data.strategy_version ?? "--"],
                ["experiment_id", run.data.experiment_id ?? "--"],
                ["开始时间", formatTime(run.data.started_at, true)],
                ["结束时间", formatTime(run.data.finished_at, true)],
              ].map(([label, value]) => (
                <div key={String(label)} className="bg-ink-850 p-4">
                  <div className="text-[11px] text-slate-500">{label}</div>
                  <div className="mt-2 truncate font-mono text-xs text-slate-200" title={String(value)}>
                    {String(value)}
                  </div>
                </div>
              ))}
            </div>
            {run.data.error && (
              <div className="border-t border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
                {run.data.error}
              </div>
            )}
          </section>

          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(320px,.6fr)]">
            <section className="panel overflow-hidden">
              <div className="panel-header">
                <h3 className="section-title">运行事件</h3>
                <span className="muted">{events.data?.length ?? 0} 条</span>
              </div>
              <EventTable events={events.data ?? []} />
            </section>
            <section className="panel overflow-hidden">
              <div className="panel-header">
                <h3 className="section-title">运行指标</h3>
              </div>
              <JsonViewer value={metrics.data ?? run.data.metrics} className="p-3" />
            </section>
          </div>
        </>
      )}
    </div>
  );
}
