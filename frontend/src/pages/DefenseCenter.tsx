import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BrainCircuit,
  GitBranch,
  KeyRound,
  RotateCcw,
  ShieldAlert,
  ShieldCheck,
  Wrench,
} from "lucide-react";
import { api } from "../lib/api";
import { parseEdge, getErrorMessage } from "../lib/utils";
import { useAppStore } from "../store/app-store";
import { JsonViewer } from "../components/common/JsonViewer";

function ContainmentList({
  title,
  items,
  icon: Icon,
  onRelease,
  extra,
}: {
  title: string;
  items: string[];
  icon: typeof ShieldAlert;
  onRelease: (item: string) => void;
  extra?: (item: string) => React.ReactNode;
}) {
  return (
    <section className="panel overflow-hidden">
      <div className="panel-header">
        <div className="flex items-center gap-2">
          <Icon className="size-4 text-cyan-350" />
          <h3 className="section-title">{title}</h3>
        </div>
        <span className="muted">{items.length}</span>
      </div>
      <div className="max-h-72 divide-y divide-slate-800 overflow-auto">
        {!items.length && <div className="p-5 text-center text-xs text-slate-500">当前为空</div>}
        {items.map((item) => (
          <div key={item} className="flex items-center gap-2 px-4 py-3">
            <span className="min-w-0 flex-1 truncate font-mono text-xs text-slate-300">{item}</span>
            {extra?.(item)}
            <button type="button" className="btn h-8" onClick={() => onRelease(item)}>
              <RotateCcw className="size-3.5" />
              释放
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}

export function DefenseCenter() {
  const queryClient = useQueryClient();
  const addToast = useAppStore((state) => state.addToast);
  const containment = useQuery({
    queryKey: ["containment"],
    queryFn: api.getContainmentStatus,
    refetchInterval: 4_000,
  });
  const memory = useQuery({
    queryKey: ["defense-memory"],
    queryFn: api.getDefenseMemory,
    refetchInterval: 5_000,
  });
  const decisions = useQuery({
    queryKey: ["defense-decisions"],
    queryFn: api.getDefenseDecisions,
    refetchInterval: 5_000,
  });
  const action = useMutation({
    mutationFn: async ({
      type,
      value,
    }: {
      type: "node" | "tool" | "edge" | "memory" | "check" | "approve";
      value: string;
    }) => {
      if (type === "node") return api.releaseNode(value);
      if (type === "tool") return api.releaseTool(value);
      if (type === "memory") return api.releaseMemoryKey(value);
      if (type === "check") return api.checkRecovery(value);
      if (type === "approve") return api.approveRecovery(value);
      const { source, target } = parseEdge(value);
      return api.releaseEdge(source, target);
    },
    onSuccess: async (result, variables) => {
      await queryClient.invalidateQueries({ queryKey: ["containment"] });
      addToast(
        variables.type === "check"
          ? `恢复检查：${String(result.reason ?? result.can_recover ?? "完成")}`
          : "防御状态已更新",
        "success",
      );
    },
    onError: (error) => addToast(getErrorMessage(error), "error"),
  });

  const status = containment.data ?? {
    quarantined_nodes: [],
    isolated_tools: [],
    blocked_edges: [],
    revoked_memory_keys: [],
  };

  return (
    <div className="space-y-4 p-5">
      <div>
        <h2 className="text-xl font-semibold text-white">联合防御中心</h2>
        <p className="mt-1 text-xs text-slate-500">
          管理动态隔离、恢复审批、威胁记忆与联合防御裁决。
        </p>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <ContainmentList
          title="隔离节点"
          items={status.quarantined_nodes}
          icon={ShieldAlert}
          onRelease={(value) => action.mutate({ type: "node", value })}
          extra={(value) => (
            <>
              <button type="button" className="btn h-8 px-2" onClick={() => action.mutate({ type: "check", value })}>
                检查恢复
              </button>
              <button type="button" className="btn h-8 px-2" onClick={() => action.mutate({ type: "approve", value })}>
                批准恢复
              </button>
            </>
          )}
        />
        <ContainmentList
          title="隔离工具"
          items={status.isolated_tools}
          icon={Wrench}
          onRelease={(value) => action.mutate({ type: "tool", value })}
        />
        <ContainmentList
          title="阻断传播边"
          items={status.blocked_edges}
          icon={GitBranch}
          onRelease={(value) => action.mutate({ type: "edge", value })}
        />
        <ContainmentList
          title="撤销记忆键"
          items={status.revoked_memory_keys}
          icon={KeyRound}
          onRelease={(value) => action.mutate({ type: "memory", value })}
        />
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <section className="panel overflow-hidden">
          <div className="panel-header">
            <div className="flex items-center gap-2">
              <BrainCircuit className="size-4 text-cyan-350" />
              <h3 className="section-title">威胁记忆</h3>
            </div>
          </div>
          <JsonViewer value={memory.data ?? {}} className="h-[480px] p-3" />
        </section>
        <section className="panel overflow-hidden">
          <div className="panel-header">
            <div className="flex items-center gap-2">
              <ShieldCheck className="size-4 text-cyan-350" />
              <h3 className="section-title">最近防御决策</h3>
            </div>
            <span className="muted">{decisions.data?.items.length ?? 0}</span>
          </div>
          <JsonViewer value={decisions.data?.items ?? []} className="h-[480px] p-3" />
        </section>
      </div>
    </div>
  );
}
