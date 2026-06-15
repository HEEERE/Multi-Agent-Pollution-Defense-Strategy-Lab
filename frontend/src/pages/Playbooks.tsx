import { useMutation, useQuery } from "@tanstack/react-query";
import {
  BookOpen,
  BrainCircuit,
  CheckCircle2,
  Play,
  ShieldAlert,
  ShieldCheck,
  Wrench,
} from "lucide-react";
import { useState } from "react";
import { api } from "../lib/api";
import type { AgentEvent, Playbook } from "../lib/types";
import { getErrorMessage } from "../lib/utils";
import { useAppStore } from "../store/app-store";
import { EventTable } from "../components/events/EventTable";
import { Loading } from "../components/common/Loading";

const meta: Record<
  string,
  { title: string; category: string; icon: typeof ShieldAlert; tone: string }
> = {
  "a-explicit-privilege-escalation": {
    title: "显式权限提升",
    category: "提示注入",
    icon: ShieldAlert,
    tone: "text-red-300 bg-red-500/10",
  },
  "b-covert-context-poisoning": {
    title: "隐蔽上下文污染",
    category: "RAG 污染",
    icon: BrainCircuit,
    tone: "text-amber-300 bg-amber-500/10",
  },
  "c-cognitive-deception-quarantine": {
    title: "认知欺骗隔离",
    category: "意图检测",
    icon: ShieldCheck,
    tone: "text-violet-300 bg-violet-500/10",
  },
  "d-safe-collaboration": {
    title: "安全协作",
    category: "良性基线",
    icon: CheckCircle2,
    tone: "text-emerald-300 bg-emerald-500/10",
  },
  "e-tool-memory-contamination": {
    title: "工具记忆污染",
    category: "工具安全",
    icon: Wrench,
    tone: "text-red-300 bg-red-500/10",
  },
  "f-monitor-recovery": {
    title: "监控器恢复",
    category: "恢复流程",
    icon: ShieldCheck,
    tone: "text-sky-300 bg-sky-500/10",
  },
};

export function Playbooks() {
  const addToast = useAppStore((state) => state.addToast);
  const [active, setActive] = useState<Playbook | null>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const playbooks = useQuery({ queryKey: ["playbooks"], queryFn: api.listPlaybooks });
  const run = useMutation({
    mutationFn: (id: string) => api.runPlaybook(id),
    onSuccess: (result) => {
      setEvents(result);
      addToast(`剧本运行完成，共产生 ${result.length} 个事件`, "success");
    },
    onError: (error) => addToast(getErrorMessage(error), "error"),
  });

  return (
    <div className="space-y-4 p-5">
      <div>
        <h2 className="text-xl font-semibold text-white">攻击与防御剧本</h2>
        <p className="mt-1 text-xs text-slate-500">
          运行内置场景，产生的事件会写入 Event Store 并同步到全局实时流。
        </p>
      </div>
      {playbooks.isLoading ? (
        <section className="panel"><Loading /></section>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
          {(playbooks.data ?? []).map((playbook) => {
            const item = meta[playbook.id] ?? {
              title: playbook.name,
              category: "安全剧本",
              icon: BookOpen,
              tone: "text-cyan-300 bg-cyan-500/10",
            };
            const Icon = item.icon;
            return (
              <article
                key={playbook.id}
                className={`panel p-5 transition hover:border-slate-500 ${
                  active?.id === playbook.id ? "border-cyan-450" : ""
                }`}
              >
                <div className="flex items-start justify-between">
                  <div className={`grid size-11 place-items-center rounded-xl ${item.tone}`}>
                    <Icon className="size-5" />
                  </div>
                  <span className="rounded-md border border-slate-700 px-2 py-1 text-[10px] text-slate-400">
                    {item.category}
                  </span>
                </div>
                <h3 className="mt-4 text-base font-semibold text-white">{item.title}</h3>
                <p className="mt-2 min-h-12 text-xs leading-5 text-slate-500">
                  {playbook.description}
                </p>
                <button
                  type="button"
                  className="btn-primary mt-4 w-full"
                  disabled={run.isPending}
                  onClick={() => {
                    setActive(playbook);
                    setEvents([]);
                    run.mutate(playbook.id);
                  }}
                >
                  <Play className="size-4" />
                  运行剧本
                </button>
              </article>
            );
          })}
        </div>
      )}
      <section className="panel overflow-hidden">
        <div className="panel-header">
          <div>
            <h3 className="section-title">剧本输出事件</h3>
            <p className="muted mt-1">{active ? meta[active.id]?.title ?? active.name : "尚未运行剧本"}</p>
          </div>
          <span className="muted">{events.length} 条</span>
        </div>
        <EventTable events={events} />
      </section>
    </div>
  );
}
