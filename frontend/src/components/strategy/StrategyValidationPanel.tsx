import { CheckCircle2, CircleAlert, Info } from "lucide-react";
import type { StrategyValidationResult } from "../../lib/types";

export function StrategyValidationPanel({
  result,
  localIssues,
}: {
  result?: StrategyValidationResult;
  localIssues: string[];
}) {
  const issues = [
    ...localIssues.map((message) => ({ path: "frontend", message, level: "warning" })),
    ...(result?.issues ?? []),
  ];
  return (
    <div>
      <div className="flex items-center gap-4 border-b border-slate-800 px-4 py-3 text-xs">
        <div className="flex items-center gap-2 text-emerald-300">
          <CheckCircle2 className="size-4" />
          {result?.valid ? "后端校验通过" : "等待校验"}
        </div>
        <div className="flex items-center gap-2 text-amber-300">
          <CircleAlert className="size-4" />
          {issues.filter((item) => item.level !== "info").length} 个问题
        </div>
      </div>
      <div className="max-h-56 divide-y divide-slate-800 overflow-auto">
        {!issues.length && (
          <div className="flex items-center gap-2 px-4 py-5 text-xs text-slate-500">
            <Info className="size-4" />
            尚未发现问题。后端校验结果为最终依据。
          </div>
        )}
        {issues.map((issue, index) => (
          <div key={`${issue.path}-${index}`} className="flex gap-3 px-4 py-3">
            <CircleAlert
              className={`mt-0.5 size-4 shrink-0 ${
                issue.level === "error" ? "text-red-400" : "text-amber-400"
              }`}
            />
            <div className="min-w-0 text-xs">
              <div className="font-mono text-slate-500">{issue.path}</div>
              <div className="mt-1 leading-5 text-slate-300">{issue.message}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
