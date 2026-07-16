import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Braces,
  CheckCircle2,
  Clock3,
  FilePlus2,
  Play,
  Save,
  Search,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { defaultStrategyContent } from "../lib/defaults";
import type {
  AgentEvent,
  JsonObject,
  StrategyRead,
  StrategyValidationResult,
} from "../lib/types";
import { connectRunEvents, isAgentEvent } from "../lib/ws";
import { formatTime, getErrorMessage, safeJsonParse } from "../lib/utils";
import { useAppStore } from "../store/app-store";
import { JsonViewer } from "../components/common/JsonViewer";
import { StatusBadge } from "../components/common/StatusBadge";
import { EventTimeline } from "../components/events/EventTimeline";
import { StrategyEditor } from "../components/strategy/StrategyEditor";
import { StrategyValidationPanel } from "../components/strategy/StrategyValidationPanel";

function localValidate(content: JsonObject) {
  const issues: string[] = [];
  const topology = content.topology as JsonObject | undefined;
  if (!topology) return ["缺少 topology 对象"];
  const nodes = topology.nodes;
  if (!Array.isArray(nodes) || !nodes.length) issues.push("topology.nodes 至少需要一个节点");
  if (Array.isArray(nodes)) {
    const allowed = new Set(["gateway", "agent", "tool", "monitor", "memory"]);
    nodes.forEach((node, index) => {
      const type = (node as JsonObject).node_type;
      if (!allowed.has(String(type))) issues.push(`nodes[${index}].node_type 不受支持`);
    });
  }
  const maxTurns = Number(topology.max_turns ?? 5);
  if (maxTurns < 1 || maxTurns > 100) issues.push("max_turns 必须在 1 到 100 之间");
  else if (maxTurns > 50) issues.push("max_turns 超过 50，运行时间可能较长");
  return issues;
}

export function StrategyLab() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const addToast = useAppStore((state) => state.addToast);
  // undefined means initial load; null is an intentional unsaved draft.
  const [selectedId, setSelectedId] = useState<string | null | undefined>();
  const [name, setName] = useState("demo-strategy");
  const [description, setDescription] = useState("用于提示注入传播防御的演示策略。");
  const [tags, setTags] = useState("提示注入, 联合防御");
  const [editorValue, setEditorValue] = useState(
    JSON.stringify(defaultStrategyContent, null, 2),
  );
  const [validation, setValidation] = useState<StrategyValidationResult>();
  const [runId, setRunId] = useState<string | null>(null);
  const [streamEvents, setStreamEvents] = useState<AgentEvent[]>([]);
  const [search, setSearch] = useState("");

  const strategies = useQuery({
    queryKey: ["strategies"],
    queryFn: api.listStrategies,
  });

  useEffect(() => {
    if (selectedId === undefined && strategies.data?.length) {
      setSelectedId(strategies.data[0].strategy_id);
    }
  }, [selectedId, strategies.data]);

  const selected = strategies.data?.find((item) => item.strategy_id === selectedId);
  useEffect(() => {
    if (!selected) return;
    setName(selected.name);
    setDescription(selected.description);
    setTags(selected.tags.join(", "));
    setEditorValue(JSON.stringify(selected.content, null, 2));
    setValidation(undefined);
    setRunId(null);
    setStreamEvents([]);
  }, [selected]);

  const parsedContent = useMemo(() => {
    try {
      return safeJsonParse(editorValue);
    } catch {
      return null;
    }
  }, [editorValue]);
  const localIssues = parsedContent ? localValidate(parsedContent) : ["JSON 语法无效"];
  const isDirty = useMemo(() => {
    if (!selected || !parsedContent) return true;
    const normalizedTags = tags.split(",").map((tag) => tag.trim()).filter(Boolean);
    return (
      name.trim() !== selected.name ||
      description.trim() !== selected.description ||
      JSON.stringify(normalizedTags) !== JSON.stringify(selected.tags) ||
      JSON.stringify(parsedContent) !== JSON.stringify(selected.content)
    );
  }, [description, name, parsedContent, selected, tags]);

  const validate = useMutation({
    mutationFn: async () => {
      if (!parsedContent) throw new Error("请先修复 JSON 语法");
      return api.validateStrategy(parsedContent);
    },
    onSuccess: (result) => {
      setValidation(result);
      addToast(result.valid ? "策略校验通过" : "策略校验未通过", result.valid ? "success" : "error");
    },
    onError: (error) => addToast(getErrorMessage(error), "error"),
  });

  const save = useMutation({
    mutationFn: async () => {
      if (!parsedContent) throw new Error("请先修复 JSON 语法");
      const payload = {
        name: name.trim(),
        description: description.trim(),
        format: "json" as const,
        content: parsedContent,
        tags: tags.split(",").map((tag) => tag.trim()).filter(Boolean),
      };
      return selectedId
        ? api.updateStrategy(selectedId, payload)
        : api.createStrategy(payload);
    },
    onSuccess: async (strategy) => {
      setSelectedId(strategy.strategy_id);
      await queryClient.invalidateQueries({ queryKey: ["strategies"] });
      addToast("策略已保存", "success");
    },
    onError: (error) => addToast(getErrorMessage(error), "error"),
  });

  const remove = useMutation({
    mutationFn: () => api.deleteStrategy(selectedId!),
    onSuccess: async () => {
      setSelectedId(null);
      await queryClient.invalidateQueries({ queryKey: ["strategies"] });
      newStrategy();
      addToast("策略已删除", "success");
    },
    onError: (error) => addToast(getErrorMessage(error), "error"),
  });

  const run = useMutation({
    mutationFn: () => api.runStrategy(selectedId!),
    onSuccess: (result) => {
      setRunId(result.run_id);
      setStreamEvents([]);
      addToast(`运行已启动：${result.run_id}`, "success");
    },
    onError: (error) => addToast(getErrorMessage(error), "error"),
  });

  const runQuery = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.getRun(runId!),
    enabled: Boolean(runId),
    refetchInterval: (query) =>
      ["completed", "failed", "cancelled"].includes(
        query.state.data?.status ?? "",
      )
        ? false
        : 1_500,
  });
  const runEvents = useQuery({
    queryKey: ["run-events", runId],
    queryFn: () => api.getRunEvents(runId!),
    enabled: Boolean(runId),
    refetchInterval: ["completed", "failed", "cancelled"].includes(
      runQuery.data?.status ?? "",
    )
      ? false
      : 1_500,
  });
  const runMetrics = useQuery({
    queryKey: ["run-metrics", runId],
    queryFn: () => api.getRunMetrics(runId!),
    enabled:
      Boolean(runId) &&
      ["completed", "failed", "cancelled"].includes(runQuery.data?.status ?? ""),
  });

  useEffect(() => {
    if (!runId) return;
    return connectRunEvents(runId, (message) => {
      if (isAgentEvent(message)) {
        setStreamEvents((current) => [
          message,
          ...current.filter((item) => item.event_id !== message.event_id),
        ]);
      }
    });
  }, [runId]);

  const combinedRunEvents = useMemo(() => {
    const map = new Map<string, AgentEvent>();
    [...streamEvents, ...(runEvents.data ?? [])].forEach((event) =>
      map.set(event.event_id, event),
    );
    return [...map.values()].sort((a, b) => b.timestamp - a.timestamp);
  }, [runEvents.data, streamEvents]);

  function newStrategy() {
    setSelectedId(null);
    setName("demo-strategy");
    setDescription("用于提示注入传播防御的演示策略。");
    setTags("提示注入, 联合防御");
    setEditorValue(JSON.stringify(defaultStrategyContent, null, 2));
    setValidation(undefined);
    setRunId(null);
    setStreamEvents([]);
  }

  const visibleStrategies = (strategies.data ?? []).filter(
    (item) =>
      item.name.toLowerCase().includes(search.toLowerCase()) ||
      item.tags.some((tag) => tag.toLowerCase().includes(search.toLowerCase())),
  );

  return (
    <div className="grid min-h-full grid-cols-[200px_minmax(0,1fr)_300px] bg-ink-950 xl:grid-cols-[220px_minmax(0,1fr)_340px] min-[1360px]:grid-cols-[260px_minmax(480px,1fr)_400px]">
      <aside className="flex min-h-0 flex-col bg-[#07141f]">
        <div className="flex h-12 items-center justify-between border-b border-slate-800 px-3">
          <h2 className="section-title">策略列表</h2>
          <button type="button" onClick={newStrategy} className="btn h-8 px-2">
            <FilePlus2 className="size-3.5" />
            新建
          </button>
        </div>
        <div className="p-3">
          <label className="relative block">
            <Search className="absolute left-3 top-3 size-4 text-slate-500" />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              className="input pl-9"
              placeholder="搜索策略或标签"
            />
          </label>
        </div>
        <div className="min-h-0 flex-1 space-y-2 overflow-auto px-2 pb-3">
          {!visibleStrategies.length && (
            <div className="rounded-lg border border-dashed border-slate-700 p-4 text-center text-xs text-slate-500">
              暂无已保存策略，使用默认模板新建一个。
            </div>
          )}
          {visibleStrategies.map((strategy) => (
            <button
              type="button"
              key={strategy.strategy_id}
              onClick={() => setSelectedId(strategy.strategy_id)}
              className={`w-full rounded-lg border p-3 text-left transition ${
                selectedId === strategy.strategy_id
                  ? "border-cyan-450 bg-cyan-450/10"
                  : "border-slate-800 bg-ink-900 hover:border-slate-600"
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-xs font-medium text-slate-200">
                  {strategy.name}
                </span>
                <span className="font-mono text-[10px] text-slate-500">
                  v{strategy.version}
                </span>
              </div>
              <p className="mt-2 line-clamp-2 text-[11px] leading-4 text-slate-500">
                {strategy.description || "无描述"}
              </p>
              <div className="mt-2 text-[10px] text-slate-600">
                {formatTime(strategy.updated_at, true)}
              </div>
            </button>
          ))}
        </div>
      </aside>

      <div className="flex min-h-0 flex-col">
        <div className="grid grid-cols-[1fr_1.35fr] gap-3 border-b border-slate-800 bg-[#07141f] p-3">
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="策略名称" />
          <input className="input" value={tags} onChange={(e) => setTags(e.target.value)} placeholder="标签，以逗号分隔" />
          <input className="input col-span-2" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="策略说明" />
        </div>
        <StrategyEditor value={editorValue} onChange={setEditorValue} />
      </div>

      <aside className="min-h-0 overflow-auto bg-[#07141f]">
        <div className="grid grid-cols-3 gap-2 border-b border-slate-800 p-3">
          <button type="button" onClick={() => validate.mutate()} disabled={validate.isPending} className="btn">
            <CheckCircle2 className="size-4" />校验
          </button>
          <button type="button" onClick={() => save.mutate()} disabled={save.isPending} className="btn">
            <Save className="size-4" />保存
          </button>
          <button
            type="button"
            onClick={() => run.mutate()}
            disabled={!selectedId || isDirty || run.isPending}
            title={isDirty ? "请先保存当前修改后再运行" : undefined}
            className="btn-primary"
          >
            <Play className="size-4" />运行
          </button>
        </div>

        <section className="border-b border-slate-800">
          <div className="panel-header">
            <h3 className="section-title">校验结果</h3>
            {validation && <StatusBadge status={validation.valid ? "completed" : "failed"} />}
          </div>
          <StrategyValidationPanel result={validation} localIssues={localIssues} />
        </section>

        <section className="border-b border-slate-800">
          <div className="panel-header">
            <h3 className="section-title">实时运行</h3>
            {runQuery.data && <StatusBadge status={runQuery.data.status} />}
          </div>
          <div className="space-y-3 p-4 text-xs">
            <div className="grid grid-cols-[70px_1fr] gap-2">
              <span className="text-slate-500">run_id</span>
              <span className="break-all font-mono text-violet-300">{runId ?? "--"}</span>
              <span className="text-slate-500">trace_id</span>
              <span className="break-all font-mono text-cyan-300">{runQuery.data?.trace_id ?? "--"}</span>
              <span className="text-slate-500">开始时间</span>
              <span className="text-slate-300">{formatTime(runQuery.data?.started_at)}</span>
            </div>
            {runQuery.data?.error && (
              <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-red-300">
                {runQuery.data.error}
              </div>
            )}
            {runQuery.data?.trace_id && (
              <button
                type="button"
                onClick={() => navigate(`/traces?trace=${runQuery.data?.trace_id}`)}
                className="btn w-full border-cyan-450/50 text-cyan-300"
              >
                查看 Trace
              </button>
            )}
          </div>
        </section>

        <section className="border-b border-slate-800">
          <div className="panel-header">
            <h3 className="section-title">实时事件</h3>
            <span className="muted">{combinedRunEvents.length} 条</span>
          </div>
          <div className="max-h-72 overflow-auto">
            <EventTimeline events={combinedRunEvents} limit={10} />
          </div>
        </section>

        <section>
          <div className="panel-header">
            <h3 className="section-title">运行指标</h3>
            <Clock3 className="size-4 text-cyan-350" />
          </div>
          <JsonViewer value={runMetrics.data ?? runQuery.data?.metrics ?? {}} className="p-3" />
        </section>

        {selectedId && (
          <div className="p-3">
            <button
              type="button"
              onClick={() => {
                if (window.confirm("确定删除当前策略？")) remove.mutate();
              }}
              className="btn-danger w-full"
            >
              <Trash2 className="size-4" />
              删除当前策略
            </button>
          </div>
        )}
      </aside>
    </div>
  );
}
