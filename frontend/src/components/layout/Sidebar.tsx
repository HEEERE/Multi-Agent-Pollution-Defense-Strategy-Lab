import {
  Activity,
  BarChart3,
  BookOpen,
  FlaskConical,
  Gauge,
  History,
  PlaySquare,
  Route,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
} from "lucide-react";
import { NavLink } from "react-router-dom";
import { cn } from "../../lib/utils";

const items = [
  { to: "/", label: "总览", icon: Gauge, end: true },
  { to: "/strategies", label: "策略实验室", icon: SlidersHorizontal },
  { to: "/runs", label: "运行监控", icon: Activity },
  { to: "/traces", label: "链路追踪", icon: Route },
  { to: "/replay", label: "事件回放", icon: History },
  { to: "/playbooks", label: "攻击剧本", icon: BookOpen },
  { to: "/experiments", label: "实验管理", icon: FlaskConical },
  { to: "/benchmark", label: "基准测试", icon: BarChart3 },
  { to: "/defense", label: "防御中心", icon: ShieldCheck },
  { to: "/settings", label: "系统设置", icon: Settings },
];

export function Sidebar() {
  return (
    <aside className="fixed inset-y-0 left-0 z-40 flex w-[var(--sidebar-width)] flex-col border-r border-slate-800 bg-[#04101a]">
      <div className="flex h-[var(--topbar-height)] items-center gap-3 border-b border-slate-800 px-4">
        <div className="grid size-9 place-items-center rounded-lg border border-cyan-450/40 bg-cyan-450/10 text-cyan-350 shadow-glow">
          <ShieldCheck className="size-5" />
        </div>
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-white">MAJD-Guard</div>
          <div className="truncate text-[10px] text-cyan-350">联合防御策略实验室</div>
        </div>
      </div>

      <nav className="flex-1 space-y-1 overflow-y-auto p-2">
        {items.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              cn(
                "relative flex h-11 items-center gap-3 rounded-lg px-3 text-sm text-slate-400 transition hover:bg-slate-800/60 hover:text-slate-100",
                isActive &&
                  "bg-cyan-450/10 text-cyan-350 before:absolute before:-left-2 before:h-7 before:w-0.5 before:bg-cyan-350",
              )
            }
          >
            <Icon className="size-[18px] shrink-0" />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-slate-800 p-3">
        <div className="rounded-lg border border-slate-800 bg-ink-900 p-3">
          <div className="flex items-center gap-2 text-xs text-slate-300">
            <PlaySquare className="size-4 text-cyan-350" />
            实验模式
          </div>
          <p className="mt-1 text-[10px] leading-4 text-slate-500">
            数据来自 FastAPI 实时接口，不使用硬编码业务数据。
          </p>
        </div>
      </div>
    </aside>
  );
}
