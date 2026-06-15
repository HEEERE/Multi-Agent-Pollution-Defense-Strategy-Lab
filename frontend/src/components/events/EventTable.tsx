import { Inbox } from "lucide-react";
import type { AgentEvent } from "../../lib/types";
import { compactId, formatTime } from "../../lib/utils";
import { EmptyState } from "../common/EmptyState";
import { StatusBadge } from "../common/StatusBadge";

export function EventTable({ events }: { events: AgentEvent[] }) {
  if (!events.length) {
    return (
      <EmptyState
        icon={Inbox}
        title="暂无事件"
        description="当前运行还没有产生可展示的事件。"
      />
    );
  }
  return (
    <div className="overflow-auto">
      <table className="w-full min-w-[760px] text-left text-xs">
        <thead className="sticky top-0 bg-ink-800 text-slate-400">
          <tr>
            <th className="px-4 py-3 font-medium">时间</th>
            <th className="px-4 py-3 font-medium">传播路径</th>
            <th className="px-4 py-3 font-medium">类型</th>
            <th className="px-4 py-3 font-medium">状态</th>
            <th className="px-4 py-3 font-medium">动作</th>
            <th className="px-4 py-3 font-medium">trace_id</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800">
          {events.map((event) => (
            <tr key={event.event_id} className="hover:bg-slate-800/30">
              <td className="whitespace-nowrap px-4 py-3 font-mono text-slate-500">
                {formatTime(event.timestamp)}
              </td>
              <td className="max-w-72 px-4 py-3">
                <div className="text-slate-200">
                  {event.source_node} → {event.target_node}
                </div>
                <div className="mt-1 truncate text-slate-500">{event.payload_snippet}</div>
              </td>
              <td className="px-4 py-3 text-slate-400">{event.event_type}</td>
              <td className="px-4 py-3"><StatusBadge status={event.status} /></td>
              <td className="px-4 py-3 text-slate-400">{event.action_taken}</td>
              <td className="px-4 py-3 font-mono text-slate-500">
                {compactId(event.trace_id, 20)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
