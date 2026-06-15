import { useQuery } from "@tanstack/react-query";
import { Activity, Cpu, Radio, ShieldAlert, ShieldCheck } from "lucide-react";
import { useEffect } from "react";
import { api } from "../lib/api";
import { compactId } from "../lib/utils";
import { useAppStore } from "../store/app-store";
import { MetricCard } from "../components/common/MetricCard";
import { Loading } from "../components/common/Loading";
import { StatusBadge } from "../components/common/StatusBadge";
import { EventTimeline } from "../components/events/EventTimeline";

export function Dashboard() {
  const liveEvents = useAppStore((state) => state.liveEvents);
  const seedLiveEvents = useAppStore((state) => state.seedLiveEvents);
  const wsStatus = useAppStore((state) => state.wsStatus);
  const health = useQuery({ queryKey: ["health"], queryFn: api.getHealth });
  const platform = useQuery({
    queryKey: ["platform-config"],
    queryFn: api.getPlatformConfig,
  });
  const latest = useQuery({
    queryKey: ["events", "latest"],
    queryFn: () => api.getLatestEvents(20),
  });
  const containment = useQuery({
    queryKey: ["containment"],
    queryFn: api.getContainmentStatus,
    refetchInterval: 5_000,
  });
  const decisions = useQuery({
    queryKey: ["defense-decisions"],
    queryFn: api.getDefenseDecisions,
    refetchInterval: 5_000,
  });

  useEffect(() => {
    if (latest.data) seedLiveEvents(latest.data);
  }, [latest.data, seedLiveEvents]);

  const containmentCount = containment.data
    ? containment.data.quarantined_nodes.length +
      containment.data.isolated_tools.length +
      containment.data.blocked_edges.length +
      containment.data.revoked_memory_keys.length
    : 0;

  return (
    <div className="space-y-4 p-5">
      <div>
        <h2 className="text-xl font-semibold text-white">多智能体污染态势</h2>
        <p className="mt-1 text-xs text-slate-500">
          汇总后端状态、实时事件、联合防御决策与动态隔离范围。
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          label="后端状态"
          value={health.isSuccess ? "在线" : "离线"}
          helper={health.data?.service ?? health.error?.message ?? "FastAPI"}
          icon={Activity}
          tone={health.isSuccess ? "green" : "red"}
        />
        <MetricCard
          label="大模型状态"
          value={platform.data?.llm_ready ? "已就绪" : "未就绪"}
          helper={platform.data?.llm_model ?? "等待平台配置"}
          icon={Cpu}
          tone={platform.data?.llm_ready ? "cyan" : "amber"}
        />
        <MetricCard
          label="活动隔离"
          value={containmentCount}
          helper="节点、工具、边与记忆键"
          icon={ShieldAlert}
          tone={containmentCount ? "violet" : "green"}
        />
        <MetricCard
          label="实时事件"
          value={liveEvents.length}
          helper={wsStatus === "connected" ? "WebSocket 正常" : "正在重连"}
          icon={Radio}
          tone={wsStatus === "connected" ? "cyan" : "amber"}
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(360px,.65fr)]">
        <section className="panel min-h-[520px] overflow-hidden">
          <div className="panel-header">
            <div>
              <h3 className="section-title">实时事件时间线</h3>
              <p className="muted mt-1">全局 WebSocket 与最新事件查询合并展示</p>
            </div>
            <StatusBadge status={wsStatus} />
          </div>
          {latest.isLoading && !liveEvents.length ? (
            <Loading label="正在连接事件流" />
          ) : (
            <EventTimeline events={liveEvents} />
          )}
        </section>

        <div className="space-y-4">
          <section className="panel overflow-hidden">
            <div className="panel-header">
              <h3 className="section-title">隔离状态摘要</h3>
              <ShieldCheck className="size-4 text-cyan-350" />
            </div>
            <div className="grid grid-cols-2 gap-px bg-slate-800">
              {[
                ["隔离节点", containment.data?.quarantined_nodes.length ?? 0],
                ["隔离工具", containment.data?.isolated_tools.length ?? 0],
                ["阻断边", containment.data?.blocked_edges.length ?? 0],
                ["撤销记忆", containment.data?.revoked_memory_keys.length ?? 0],
              ].map(([label, value]) => (
                <div key={String(label)} className="bg-ink-850 p-4">
                  <div className="text-xs text-slate-500">{label}</div>
                  <div className="mt-1 text-2xl font-semibold text-white">{value}</div>
                </div>
              ))}
            </div>
          </section>

          <section className="panel min-h-[300px] overflow-hidden">
            <div className="panel-header">
              <h3 className="section-title">最新防御决策</h3>
              <span className="muted">{decisions.data?.items.length ?? 0} 条</span>
            </div>
            <div className="max-h-[350px] divide-y divide-slate-800 overflow-auto">
              {!decisions.data?.items.length && (
                <div className="p-6 text-center text-xs text-slate-500">
                  暂无联合防御决策
                </div>
              )}
              {decisions.data?.items
                .slice()
                .reverse()
                .slice(0, 8)
                .map((decision, index) => (
                  <div key={index} className="px-4 py-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate font-mono text-xs text-slate-300">
                        {compactId(String(decision.decision_id ?? decision.trace_id ?? `decision-${index}`), 24)}
                      </span>
                      <StatusBadge
                        status={String(decision.final_action ?? decision.action ?? "safe")}
                      />
                    </div>
                    <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">
                      {String(decision.reason ?? decision.rationale ?? "联合防御协调器已完成裁决")}
                    </p>
                  </div>
                ))}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
