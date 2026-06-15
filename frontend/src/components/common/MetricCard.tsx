import type { LucideIcon } from "lucide-react";

export function MetricCard({
  label,
  value,
  helper,
  icon: Icon,
  tone = "cyan",
}: {
  label: string;
  value: string | number;
  helper?: string;
  icon: LucideIcon;
  tone?: "cyan" | "green" | "amber" | "violet" | "red";
}) {
  const toneClass = {
    cyan: "bg-cyan-500/10 text-cyan-300",
    green: "bg-emerald-500/10 text-emerald-300",
    amber: "bg-amber-500/10 text-amber-300",
    violet: "bg-violet-500/10 text-violet-300",
    red: "bg-red-500/10 text-red-300",
  }[tone];

  return (
    <div className="panel flex min-h-28 items-center gap-3 p-3">
      <div className={`grid size-10 shrink-0 place-items-center rounded-xl ${toneClass}`}>
        <Icon className="size-5" />
      </div>
      <div className="min-w-0">
        <div className="text-xs text-slate-400">{label}</div>
        <div className="mt-1 whitespace-nowrap text-xl font-semibold text-white">{value}</div>
        {helper && <div className="mt-1 truncate text-xs text-slate-500">{helper}</div>}
      </div>
    </div>
  );
}
