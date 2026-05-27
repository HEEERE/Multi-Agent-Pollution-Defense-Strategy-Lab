import { AlertTriangle, Ban, CircleCheck, ShieldAlert } from "lucide-react";
import { useT } from "../i18n/context";
import { statusPalette } from "../graph";
import type { AgentEvent } from "../types";

const LEVEL_LABELS: Record<number, { text: string; bg: string; border: string }> = {
  1: { text: "L1 Regex", bg: "bg-blue-50", border: "border-blue-400" },
  2: { text: "L2 Semantic", bg: "bg-orange-50", border: "border-orange-400" },
  3: { text: "L3 LLM", bg: "bg-purple-50", border: "border-purple-400" },
};

function LevelBadge({ level }: { level: number }) {
  const info = LEVEL_LABELS[level];
  if (!info) return null;
  return (
    <span className={`ml-1.5 inline-flex items-center rounded border ${info.border} ${info.bg} px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide`}>
      {info.text}
    </span>
  );
}

export function EventConsole({ events, connected }: { events: AgentEvent[]; connected: boolean }) {
  const { t } = useT();
  return (
    <aside className="flex h-full min-h-0 w-full flex-col border-l border-slate-200 bg-white">
      <div className="border-b border-slate-200 px-5 py-4">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-slate-950">{t("eventConsole.title")}</h2>
          <span className="inline-flex items-center gap-2 text-xs font-medium text-slate-600">
            <span className={`h-2 w-2 rounded-full ${connected ? "bg-emerald-500" : "bg-rose-500"}`} />
            {connected ? t("eventConsole.connected") : t("eventConsole.offline")}
          </span>
        </div>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4">
        {events.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-300 px-4 py-6 text-sm text-slate-500">
            {t("eventConsole.waiting")}
          </div>
        ) : (
          events.map((event, index) => <EventRow key={`${event.timestamp}-${index}`} event={event} />)
        )}
      </div>
    </aside>
  );
}

function EventRow({ event }: { event: AgentEvent }) {
  const { t } = useT();
  const palette = statusPalette[event.status];
  const Icon = event.action_taken === "block" ? Ban : event.action_taken === "alert" ? ShieldAlert : event.status === "safe" ? CircleCheck : AlertTriangle;
  const isIntercepted = event.monitor_level > 0 && event.action_taken !== "none";
  const leftBorder = isIntercepted ? (LEVEL_LABELS[event.monitor_level]?.border ?? "border-slate-300") : "border-slate-200";

  return (
    <article className={`rounded-lg border border-l-4 bg-slate-50 p-3 ${leftBorder}`}>
      <div className="flex items-start gap-3">
        <div className="mt-0.5 rounded border bg-white p-1.5" style={{ color: palette.node, borderColor: palette.edge }}>
          <Icon size={15} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <span>{formatTime(event.timestamp)}</span>
            <span>{event.event_type}</span>
            <span style={{ color: palette.node }}>{palette.text}</span>
            {event.monitor_level > 0 && <LevelBadge level={event.monitor_level} />}
          </div>
          <div className="mt-1 text-sm font-semibold text-slate-900">
            {event.source_node} {"->"} {event.target_node}
          </div>
          <p className="mt-2 break-words text-xs leading-5 text-slate-600">{event.payload_snippet}</p>
          <div className="mt-2 text-xs font-medium text-slate-700">
            {t("eventConsole.action")}: {event.action_taken}
            {detectionReason(event.metadata) && (
              <span className="ml-2 text-slate-500">({detectionReason(event.metadata)})</span>
            )}
          </div>
        </div>
      </div>
    </article>
  );
}

function detectionReason(metadata: Record<string, unknown> | undefined): string | null {
  if (!metadata) return null;
  const det = metadata.detection;
  if (det && typeof det === "object" && "reason" in det) {
    return String((det as Record<string, unknown>).reason ?? "");
  }
  return null;
}

function formatTime(timestamp: number) {
  const date = new Date(timestamp * 1000);
  return date.toLocaleTimeString("zh-CN", { hour12: false });
}
