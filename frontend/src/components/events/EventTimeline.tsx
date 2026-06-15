import { ArrowRight, Radio } from "lucide-react";
import type { AgentEvent } from "../../lib/types";
import { compactId, formatTime } from "../../lib/utils";
import { EmptyState } from "../common/EmptyState";
import { StatusBadge } from "../common/StatusBadge";

export function EventTimeline({
  events,
  limit = 20,
}: {
  events: AgentEvent[];
  limit?: number;
}) {
  if (!events.length) {
    return (
      <EmptyState
        icon={Radio}
        title="暂无实时事件"
        description="运行攻击剧本、实验或策略后，事件会通过 WebSocket 实时出现在这里。"
      />
    );
  }

  return (
    <div className="divide-y divide-slate-800">
      {events.slice(0, limit).map((event) => (
        <div key={event.event_id} className="group flex gap-3 px-4 py-3 hover:bg-slate-800/30">
          <div className="flex w-16 shrink-0 flex-col items-end">
            <span className="font-mono text-[11px] text-slate-500">
              {formatTime(event.timestamp)}
            </span>
            <span className="mt-1 size-2 rounded-full bg-cyan-450 ring-4 ring-cyan-450/10" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-medium text-slate-200">{event.source_node}</span>
              <ArrowRight className="size-3 text-slate-600" />
              <span className="text-xs font-medium text-slate-200">{event.target_node}</span>
              <StatusBadge status={event.status} />
            </div>
            <p className="mt-1 truncate text-xs text-slate-400">{event.payload_snippet}</p>
            <div className="mt-1 font-mono text-[10px] text-slate-600">
              {event.event_type} · {compactId(event.trace_id, 22)}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
