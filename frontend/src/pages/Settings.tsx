import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCcw, Save, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { JsonObject } from "../lib/types";
import { cn, getErrorMessage, safeJsonParse } from "../lib/utils";
import { useAppStore } from "../store/app-store";

const categories = [
  { id: "detectors", label: "检测器" },
  { id: "llm", label: "大模型" },
  { id: "agents", label: "智能体" },
  { id: "system", label: "系统" },
];

export function Settings() {
  const queryClient = useQueryClient();
  const addToast = useAppStore((state) => state.addToast);
  const [category, setCategory] = useState("detectors");
  const [draft, setDraft] = useState("{}");
  const settings = useQuery({
    queryKey: ["settings", category],
    queryFn: () => api.getSettingsCategory(category),
  });
  const categoryReady =
    settings.data?.category === category && !settings.isFetching;
  useEffect(() => {
    if (settings.data?.category !== category) return;
    setDraft(JSON.stringify(settings.data.values, null, 2));
  }, [category, settings.data]);

  const save = useMutation({
    mutationFn: async () => {
      const payload: JsonObject = safeJsonParse(draft);
      return api.updateSettingsCategory(category, payload);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["settings"] });
      await queryClient.invalidateQueries({ queryKey: ["platform-config"] });
      addToast("设置已保存并应用", "success");
    },
    onError: (error) => addToast(getErrorMessage(error), "error"),
  });
  const reset = useMutation({
    mutationFn: () => api.resetSettingsCategory(category),
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ["settings", category] });
      setDraft(JSON.stringify(result.values, null, 2));
      addToast("已恢复出厂默认值", "success");
    },
    onError: (error) => addToast(getErrorMessage(error), "error"),
  });

  return (
    <div className="space-y-4 p-5">
      <div>
        <h2 className="text-xl font-semibold text-white">系统设置</h2>
        <p className="mt-1 text-xs text-slate-500">
          修改运行时配置。检测器与大模型设置保存后会触发管线重建。
        </p>
      </div>
      <section className="panel overflow-hidden">
        <div className="flex border-b border-slate-800 px-3">
          {categories.map((item) => (
            <button
              type="button"
              key={item.id}
              disabled={save.isPending || reset.isPending}
              onClick={() => {
                setDraft("{}");
                setCategory(item.id);
              }}
              className={cn("tab", category === item.id && "tab-active")}
            >
              {item.label}
            </button>
          ))}
        </div>
        {category === "llm" && (
          <div className="flex items-start gap-3 border-b border-cyan-500/20 bg-cyan-500/5 px-4 py-3 text-xs leading-5 text-cyan-200">
            <ShieldCheck className="mt-0.5 size-4 shrink-0" />
            API 密钥仅通过服务端 MIMO_API_KEY 环境变量配置，不会写入数据库或通过接口返回。
          </div>
        )}
        <textarea
          className="h-[580px] w-full resize-none bg-[#06101a] p-5 font-mono text-sm leading-6 text-slate-300 outline-none"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          disabled={!categoryReady}
          spellCheck={false}
        />
        <div className="flex justify-end gap-2 border-t border-slate-800 p-4">
          <button
            type="button"
            className="btn"
            disabled={!categoryReady || reset.isPending}
            onClick={() => window.confirm("确定重置当前分类？") && reset.mutate()}
          >
            <RotateCcw className="size-4" />
            重置分类
          </button>
          <button type="button" className="btn-primary" disabled={!categoryReady || save.isPending} onClick={() => save.mutate()}>
            <Save className="size-4" />
            保存设置
          </button>
        </div>
      </section>
    </div>
  );
}
