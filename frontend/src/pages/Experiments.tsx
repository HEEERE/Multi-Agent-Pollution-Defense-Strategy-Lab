import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, FlaskConical, Plus, Trash2, X } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { defaultExperiment } from "../lib/defaults";
import type { ExperimentRead } from "../lib/types";
import { formatTime, getErrorMessage, safeJsonParse } from "../lib/utils";
import { useAppStore } from "../store/app-store";
import { EmptyState } from "../components/common/EmptyState";
import { JsonViewer } from "../components/common/JsonViewer";
import { StatusBadge } from "../components/common/StatusBadge";

export function Experiments() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const addToast = useAppStore((state) => state.addToast);
  const [showCreate, setShowCreate] = useState(false);
  const [selected, setSelected] = useState<ExperimentRead | null>(null);
  const [draft, setDraft] = useState(JSON.stringify(defaultExperiment, null, 2));
  const experiments = useQuery({
    queryKey: ["experiments"],
    queryFn: api.listExperiments,
  });
  const create = useMutation({
    mutationFn: () => api.createExperiment(safeJsonParse(draft)),
    onSuccess: async (result) => {
      setShowCreate(false);
      setSelected(result);
      await queryClient.invalidateQueries({ queryKey: ["experiments"] });
      addToast("实验运行完成", "success");
    },
    onError: (error) => addToast(getErrorMessage(error), "error"),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.deleteExperiment(id),
    onSuccess: async () => {
      setSelected(null);
      await queryClient.invalidateQueries({ queryKey: ["experiments"] });
      addToast("实验已删除", "success");
    },
    onError: (error) => addToast(getErrorMessage(error), "error"),
  });
  const metrics = useQuery({
    queryKey: ["experiment-metrics", selected?.experiment_id],
    queryFn: () => api.getExperimentMetrics(selected!.experiment_id),
    enabled: Boolean(selected?.experiment_id),
    retry: false,
  });

  return (
    <div className="space-y-4 p-5">
      <div className="flex items-end justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-white">实验管理</h2>
          <p className="mt-1 text-xs text-slate-500">
            创建可复现实验，查看执行状态、指标并跳转到 Trace。
          </p>
        </div>
        <button type="button" className="btn-primary" onClick={() => setShowCreate(true)}>
          <Plus className="size-4" />
          创建实验
        </button>
      </div>

      <section className="panel overflow-hidden">
        <div className="panel-header">
          <h3 className="section-title">实验列表</h3>
          <span className="muted">{experiments.data?.length ?? 0} 项</span>
        </div>
        {!experiments.data?.length ? (
          <EmptyState
            icon={FlaskConical}
            title="暂无实验"
            description="创建实验后，平台会运行拓扑、记录 Trace 并计算传播指标。"
          />
        ) : (
          <div className="overflow-auto">
            <table className="w-full min-w-[760px] text-left text-xs">
              <thead className="bg-ink-800 text-slate-400">
                <tr>
                  <th className="px-4 py-3 font-medium">实验名称</th>
                  <th className="px-4 py-3 font-medium">experiment_id</th>
                  <th className="px-4 py-3 font-medium">状态</th>
                  <th className="px-4 py-3 font-medium">开始时间</th>
                  <th className="px-4 py-3 font-medium">Trace</th>
                  <th className="px-4 py-3 font-medium">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {experiments.data?.map((experiment) => (
                  <tr key={experiment.experiment_id} className="hover:bg-slate-800/30">
                    <td className="px-4 py-3 font-medium text-slate-200">{experiment.name}</td>
                    <td className="px-4 py-3 font-mono text-slate-500">{experiment.experiment_id}</td>
                    <td className="px-4 py-3"><StatusBadge status={experiment.status} /></td>
                    <td className="px-4 py-3 text-slate-500">{formatTime(experiment.started_at, true)}</td>
                    <td className="px-4 py-3 font-mono text-cyan-300">{experiment.trace_id ?? "--"}</td>
                    <td className="px-4 py-3">
                      <button type="button" className="btn h-8" onClick={() => setSelected(experiment)}>
                        查看详情
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {showCreate && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-6">
          <div className="panel w-full max-w-3xl overflow-hidden">
            <div className="panel-header">
              <div>
                <h3 className="section-title">创建实验</h3>
                <p className="muted mt-1">提交后会立即运行，可能需要数秒。</p>
              </div>
              <button type="button" className="btn h-8 w-8 px-0" onClick={() => setShowCreate(false)}>
                <X className="size-4" />
              </button>
            </div>
            <textarea
              className="h-[480px] w-full resize-none bg-[#06101a] p-4 font-mono text-xs leading-6 text-slate-300 outline-none"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
            />
            <div className="flex justify-end gap-2 border-t border-slate-800 p-4">
              <button type="button" className="btn" onClick={() => setShowCreate(false)}>取消</button>
              <button type="button" className="btn-primary" disabled={create.isPending} onClick={() => create.mutate()}>
                <FlaskConical className="size-4" />
                {create.isPending ? "正在运行" : "创建并运行"}
              </button>
            </div>
          </div>
        </div>
      )}

      {selected && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-6">
          <div className="panel grid max-h-[90vh] w-full max-w-5xl grid-cols-2 overflow-hidden">
            <div className="border-r border-slate-800">
              <div className="panel-header">
                <h3 className="section-title">{selected.name}</h3>
                <StatusBadge status={selected.status} />
              </div>
              <JsonViewer value={selected} className="h-[620px] p-3" />
            </div>
            <div>
              <div className="panel-header">
                <h3 className="section-title">实验指标</h3>
                <button type="button" className="btn h-8 w-8 px-0" onClick={() => setSelected(null)}>
                  <X className="size-4" />
                </button>
              </div>
              <JsonViewer value={metrics.data ?? { message: "指标尚不可用" }} className="h-[520px] p-3" />
              <div className="flex gap-2 border-t border-slate-800 p-4">
                {selected.trace_id && (
                  <button
                    type="button"
                    className="btn-primary flex-1"
                    onClick={() => navigate(`/traces?trace=${selected.trace_id}`)}
                  >
                    <ExternalLink className="size-4" />
                    查看 Trace
                  </button>
                )}
                <button
                  type="button"
                  className="btn-danger"
                  onClick={() => window.confirm("确定删除实验？") && remove.mutate(selected.experiment_id)}
                >
                  <Trash2 className="size-4" />
                  删除
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
