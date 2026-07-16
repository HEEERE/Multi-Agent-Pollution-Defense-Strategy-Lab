import { useMutation, useQuery } from "@tanstack/react-query";
import { Bell, CircleHelp, Cpu, LogOut, Radio, Server } from "lucide-react";
import { useLocation } from "react-router-dom";
import { api } from "../../lib/api";
import { useAppStore } from "../../store/app-store";

const titles: Record<string, string> = {
  "/": "态势总览",
  "/strategies": "策略工作台",
  "/runs": "运行监控",
  "/traces": "链路观测站",
  "/replay": "事件回放",
  "/playbooks": "攻击剧本",
  "/experiments": "实验管理",
  "/benchmark": "基准测试",
  "/defense": "防御中心",
  "/settings": "系统设置",
};

function Signal({
  ok,
  label,
  icon: Icon,
}: {
  ok: boolean;
  label: string;
  icon: typeof Server;
}) {
  return (
    <div className="flex items-center gap-2 text-xs text-slate-400">
      <span className={`size-1.5 rounded-full ${ok ? "bg-emerald-400" : "bg-red-400"}`} />
      <Icon className="size-3.5" />
      <span>{label}</span>
    </div>
  );
}

export function Topbar() {
  const location = useLocation();
  const wsStatus = useAppStore((state) => state.wsStatus);
  const health = useQuery({ queryKey: ["health"], queryFn: api.getHealth, refetchInterval: 15_000 });
  const platform = useQuery({
    queryKey: ["platform-config"],
    queryFn: api.getPlatformConfig,
    refetchInterval: 15_000,
  });
  const logout = useMutation({
    mutationFn: api.deleteAuthSession,
    onSuccess: () => window.location.reload(),
  });
  const root = `/${location.pathname.split("/")[1]}`;
  const title = titles[location.pathname] ?? titles[root] ?? "MAJD-Guard";

  return (
    <header className="fixed left-[var(--sidebar-width)] right-0 top-0 z-30 flex h-[var(--topbar-height)] items-center border-b border-slate-800 bg-[#06111bf2] px-5 backdrop-blur">
      <h1 className="min-w-48 text-lg font-semibold text-white">{title}</h1>
      <div className="ml-6 hidden flex-1 items-center gap-6 lg:flex">
        <Signal ok={health.isSuccess} label={health.isSuccess ? "后端在线" : "后端离线"} icon={Server} />
        <Signal
          ok={Boolean(platform.data?.llm_ready)}
          label={platform.data?.llm_ready ? "大模型就绪" : "大模型未就绪"}
          icon={Cpu}
        />
        <Signal
          ok={wsStatus === "connected"}
          label={wsStatus === "connected" ? "实时连接正常" : "实时连接中断"}
          icon={Radio}
        />
      </div>
      <div className="ml-auto flex items-center gap-2">
        <span className="mr-2 hidden font-mono text-xs text-slate-500 xl:block">
          {platform.data?.llm_model ?? "--"}
        </span>
        <button type="button" className="btn h-9 w-9 px-0" title="通知">
          <Bell className="size-4" />
        </button>
        <button type="button" className="btn h-9 w-9 px-0" title="帮助">
          <CircleHelp className="size-4" />
        </button>
        {platform.data?.auth_enabled && (
          <button
            type="button"
            className="btn h-9 w-9 px-0"
            title="退出登录"
            disabled={logout.isPending}
            onClick={() => logout.mutate()}
          >
            <LogOut className="size-4" />
          </button>
        )}
        <div className="ml-1 grid size-9 place-items-center rounded-full border border-slate-600 bg-ink-800 text-xs font-semibold text-slate-200">
          SE
        </div>
      </div>
    </header>
  );
}
