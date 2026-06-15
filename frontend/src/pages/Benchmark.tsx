import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BarChart3,
  Clock3,
  Gauge,
  Play,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../lib/api";
import type { BenchmarkReport } from "../lib/types";
import { formatPercent, formatTime, getErrorMessage } from "../lib/utils";
import { useAppStore } from "../store/app-store";
import { EmptyState } from "../components/common/EmptyState";
import { Loading } from "../components/common/Loading";
import { MetricCard } from "../components/common/MetricCard";

export function Benchmark() {
  const queryClient = useQueryClient();
  const addToast = useAppStore((state) => state.addToast);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const reports = useQuery({
    queryKey: ["benchmark-reports"],
    queryFn: api.listBenchmarkReports,
  });
  useEffect(() => {
    if (!selectedId && reports.data?.length) setSelectedId(reports.data[0].report_id);
  }, [reports.data, selectedId]);
  const report = useQuery({
    queryKey: ["benchmark-report", selectedId],
    queryFn: () => api.getBenchmarkReport(selectedId!),
    enabled: Boolean(selectedId),
  });
  const run = useMutation({
    mutationFn: api.runBenchmark,
    onSuccess: async (result) => {
      setSelectedId(result.report_id);
      await queryClient.invalidateQueries({ queryKey: ["benchmark-reports"] });
      addToast("Benchmark 已完成", "success");
    },
    onError: (error) => addToast(getErrorMessage(error), "error"),
  });

  const active: BenchmarkReport | undefined = report.data;
  const chartData = (active?.per_level ?? []).map((item) => ({
    name: `L${String(item.level)}`,
    recall: Number((item.recall * 100).toFixed(1)),
    fpr: Number((item.fpr * 100).toFixed(1)),
    avg: Number(item.avg_latency_ms.toFixed(1)),
    p95: Number(item.p95_latency_ms.toFixed(1)),
  }));

  return (
    <div className="space-y-4 p-5">
      <div className="flex items-end justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-white">检测基准测试</h2>
          <p className="mt-1 text-xs text-slate-500">
            使用内置攻击与安全语料衡量召回率、误报率和检测延迟。
          </p>
        </div>
        <button type="button" className="btn-primary" disabled={run.isPending} onClick={() => run.mutate()}>
          <Play className="size-4" />
          {run.isPending ? "正在运行 Benchmark" : "运行 Benchmark"}
        </button>
      </div>

      <div className="grid gap-4 xl:grid-cols-[240px_minmax(0,1fr)]">
        <aside className="panel overflow-hidden">
          <div className="panel-header">
            <h3 className="section-title">历史报告</h3>
            <span className="muted">{reports.data?.length ?? 0}</span>
          </div>
          <div className="max-h-[720px] space-y-2 overflow-auto p-2">
            {(reports.data ?? []).map((item) => (
              <button
                type="button"
                key={item.report_id}
                onClick={() => setSelectedId(item.report_id)}
                className={`w-full rounded-lg border p-3 text-left ${
                  selectedId === item.report_id
                    ? "border-cyan-450 bg-cyan-450/10"
                    : "border-slate-800 bg-ink-900"
                }`}
              >
                <div className="truncate font-mono text-xs text-slate-200">{item.report_id}</div>
                <div className="mt-2 text-[10px] text-slate-500">{formatTime(item.timestamp, true)}</div>
                <div className="mt-2 flex justify-between text-[10px]">
                  <span className="text-emerald-300">Recall {formatPercent(item.overall_recall)}</span>
                  <span className="text-amber-300">FPR {formatPercent(item.overall_fpr)}</span>
                </div>
              </button>
            ))}
          </div>
        </aside>

        <div className="space-y-4">
          {!selectedId && (
            <section className="panel">
              <EmptyState
                icon={BarChart3}
                title="暂无 Benchmark 报告"
                description="运行一次基准测试后，将生成分层召回率、误报率与延迟报告。"
              />
            </section>
          )}
          {selectedId && report.isLoading && <section className="panel"><Loading /></section>}
          {active && (
            <>
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <MetricCard label="总体召回率" value={formatPercent(active.overall_recall)} icon={ShieldCheck} tone="green" />
                <MetricCard label="总体误报率" value={formatPercent(active.overall_fpr)} icon={Gauge} tone="amber" />
                <MetricCard label="测试载荷" value={active.total_payloads} icon={BarChart3} tone="cyan" />
                <MetricCard label="真实威胁" value={active.ground_truth_threats} icon={Clock3} tone="violet" />
              </div>
              <div className="grid gap-4 xl:grid-cols-2">
                <section className="panel p-4">
                  <h3 className="section-title mb-4">召回率与误报率</h3>
                  <div className="h-72">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={chartData}>
                        <CartesianGrid stroke="#183244" strokeDasharray="3 3" />
                        <XAxis dataKey="name" stroke="#6f8798" fontSize={11} />
                        <YAxis stroke="#6f8798" fontSize={11} unit="%" />
                        <Tooltip contentStyle={{ background: "#0c1d2a", border: "1px solid #284052", borderRadius: 8 }} />
                        <Legend />
                        <Bar dataKey="recall" name="召回率" fill="#38d989" radius={[5, 5, 0, 0]} />
                        <Bar dataKey="fpr" name="误报率" fill="#f8b825" radius={[5, 5, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </section>
                <section className="panel p-4">
                  <h3 className="section-title mb-4">检测延迟</h3>
                  <div className="h-72">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={chartData}>
                        <CartesianGrid stroke="#183244" strokeDasharray="3 3" />
                        <XAxis dataKey="name" stroke="#6f8798" fontSize={11} />
                        <YAxis stroke="#6f8798" fontSize={11} unit=" ms" />
                        <Tooltip contentStyle={{ background: "#0c1d2a", border: "1px solid #284052", borderRadius: 8 }} />
                        <Legend />
                        <Line type="monotone" dataKey="avg" name="平均延迟" stroke="#31c8ff" strokeWidth={2} />
                        <Line type="monotone" dataKey="p95" name="P95 延迟" stroke="#a86bff" strokeWidth={2} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </section>
              </div>
              <section className="panel overflow-hidden">
                <div className="panel-header"><h3 className="section-title">分层指标</h3></div>
                <div className="overflow-auto">
                  <table className="w-full min-w-[900px] text-left text-xs">
                    <thead className="bg-ink-800 text-slate-400">
                      <tr>
                        {["Level", "测试数", "检出威胁", "误报", "真阴性", "Recall", "FPR", "平均延迟", "P95 延迟"].map((label) => (
                          <th key={label} className="px-4 py-3 font-medium">{label}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800">
                      {active.per_level.map((level) => (
                        <tr key={String(level.level)} className="hover:bg-slate-800/30">
                          <td className="px-4 py-3 font-mono text-cyan-300">L{String(level.level)}</td>
                          <td className="px-4 py-3">{level.total_tested}</td>
                          <td className="px-4 py-3">{level.threats_detected}</td>
                          <td className="px-4 py-3">{level.false_positives}</td>
                          <td className="px-4 py-3">{level.true_negatives}</td>
                          <td className="px-4 py-3 text-emerald-300">{formatPercent(level.recall)}</td>
                          <td className="px-4 py-3 text-amber-300">{formatPercent(level.fpr)}</td>
                          <td className="px-4 py-3">{level.avg_latency_ms.toFixed(1)} ms</td>
                          <td className="px-4 py-3">{level.p95_latency_ms.toFixed(1)} ms</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
