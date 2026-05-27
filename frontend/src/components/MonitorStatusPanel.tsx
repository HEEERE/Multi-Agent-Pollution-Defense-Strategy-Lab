import { Shield, Zap, Brain, Eye } from "lucide-react";
import { useT } from "../i18n/context";
import type { AgentEvent } from "../types";

interface LevelStat {
  level: number;
  labelKey: string;
  icon: typeof Shield;
  color: string;
  intercepted: number;
  total: number;
  lastReason: string | null;
}

function computeLevelStats(events: AgentEvent[]): LevelStat[] {
  const levels: Record<number, { intercepted: number; total: number; lastReason: string | null }> = {
    1: { intercepted: 0, total: 0, lastReason: null },
    2: { intercepted: 0, total: 0, lastReason: null },
    3: { intercepted: 0, total: 0, lastReason: null },
  };

  for (const e of events) {
    const lv = e.monitor_level;
    if (lv < 1 || lv > 3) continue;
    levels[lv].total += 1;
    if (e.action_taken !== "none") {
      levels[lv].intercepted += 1;
      const detection = e.metadata?.detection as Record<string, unknown> | undefined;
      if (detection?.reason) levels[lv].lastReason = detection.reason as string;
    }
  }

  return [
    { level: 1, labelKey: "monitor.l1", icon: Zap, color: "text-blue-600", ...levels[1] },
    { level: 2, labelKey: "monitor.l2", icon: Eye, color: "text-orange-500", ...levels[2] },
    { level: 3, labelKey: "monitor.l3", icon: Brain, color: "text-purple-600", ...levels[3] },
  ];
}

export function MonitorStatusPanel({ events }: { events: AgentEvent[] }) {
  const { t } = useT();
  const stats = computeLevelStats(events);
  const totalThreats = events.filter((e) => e.action_taken !== "none").length;
  const totalSafe = events.filter((e) => e.action_taken === "none").length;

  return (
    <div className="absolute bottom-4 right-4 z-20 w-[300px] rounded-xl border border-slate-200 bg-white/90 shadow-lg backdrop-blur">
      <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-3">
        <Shield size={16} className="text-emerald-600" />
        <span className="text-xs font-semibold text-slate-700">{t("monitor.title")}</span>
        <span className="ml-auto text-[10px] text-slate-400">
          {totalThreats} {t("monitor.threats")} / {totalSafe + totalThreats} {t("monitor.events")}
        </span>
      </div>
      <div className="space-y-2 px-3 py-3">
        {stats.map((s) => (
          <div key={s.level} className="flex items-center gap-2 rounded-md bg-slate-50 px-2 py-1.5">
            <s.icon size={14} className={s.color} />
            <span className="text-xs font-medium text-slate-700">{t(s.labelKey)}</span>
            <span className={`ml-auto text-xs font-mono font-bold ${s.intercepted > 0 ? "text-rose-600" : "text-slate-400"}`}>
              {s.intercepted}/{s.total}
            </span>
          </div>
        ))}
      </div>
      {stats.some((s) => s.lastReason) && (
        <div className="border-t border-slate-100 px-4 py-2 text-[10px] leading-relaxed text-slate-500">
          {stats.filter((s) => s.lastReason).map((s) => (
            <div key={s.level} className="truncate">
              <span className={`font-medium ${s.color}`}>{t(s.labelKey)}:</span> {s.lastReason}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
