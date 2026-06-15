import { cn } from "../../lib/utils";

const toneMap: Record<string, string> = {
  safe: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  completed: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  connected: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  exposed: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  challenged: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  warning: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  queued: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  infected: "border-red-500/40 bg-red-500/10 text-red-300",
  critical: "border-red-500/40 bg-red-500/10 text-red-300",
  failed: "border-red-500/40 bg-red-500/10 text-red-300",
  quarantined: "border-violet-500/40 bg-violet-500/10 text-violet-300",
  isolated: "border-violet-500/40 bg-violet-500/10 text-violet-300",
  recovered: "border-sky-500/40 bg-sky-500/10 text-sky-300",
  running: "border-cyan-500/40 bg-cyan-500/10 text-cyan-300",
  playing: "border-cyan-500/40 bg-cyan-500/10 text-cyan-300",
  paused: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  cancelled: "border-slate-500/40 bg-slate-500/10 text-slate-300",
};

const labelMap: Record<string, string> = {
  safe: "安全",
  completed: "已完成",
  connected: "已连接",
  exposed: "暴露",
  challenged: "受挑战",
  warning: "警告",
  queued: "排队中",
  infected: "感染",
  critical: "严重",
  failed: "失败",
  quarantined: "已隔离",
  isolated: "已隔离",
  recovered: "已恢复",
  running: "运行中",
  playing: "播放中",
  paused: "已暂停",
  cancelled: "已取消",
  disconnected: "已断开",
  connecting: "连接中",
};

export function StatusBadge({
  status,
  label,
  className,
}: {
  status: string;
  label?: string;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-medium",
        toneMap[status] ??
          "border-slate-600 bg-slate-500/10 text-slate-300",
        className,
      )}
    >
      {label ?? labelMap[status] ?? status}
    </span>
  );
}
