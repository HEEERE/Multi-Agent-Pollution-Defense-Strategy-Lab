import { AlertTriangle, Ban, CircleCheck, ShieldAlert } from "lucide-react";

import { statusPalette } from "../graph";
import type { AgentEvent } from "../types";

interface EventConsoleProps {
  events: AgentEvent[];
  connected: boolean;
}

export function EventConsole({ events, connected }: EventConsoleProps) {
  return (
    <aside className="flex h-full min-h-0 w-full flex-col border-l border-slate-200 bg-white">
      <div className="border-b border-slate-200 px-5 py-4">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-slate-950">Live Security Console</h2>
          <span className="inline-flex items-center gap-2 text-xs font-medium text-slate-600">
            <span className={`h-2 w-2 rounded-full ${connected ? "bg-emerald-500" : "bg-rose-500"}`} />
            {connected ? "Connected" : "Offline"}
          </span>
        </div>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4">
        {events.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-300 px-4 py-6 text-sm text-slate-500">
            Waiting for WebSocket events
          </div>
        ) : (
          events.map((event, index) => <EventRow key={`${event.timestamp}-${index}`} event={event} />)
        )}
      </div>
    </aside>
  );
}

function EventRow({ event }: { event: AgentEvent }) {
  const palette = statusPalette[event.status];
  const Icon = event.action_taken === "block" ? Ban : event.action_taken === "alert" ? ShieldAlert : event.status === "safe" ? CircleCheck : AlertTriangle;

  return (
    <article className="rounded-lg border border-slate-200 bg-slate-50 p-3">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 rounded border bg-white p-1.5" style={{ color: palette.node, borderColor: palette.edge }}>
          <Icon size={15} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <span>{formatTime(event.timestamp)}</span>
            <span>{event.event_type}</span>
            <span style={{ color: palette.node }}>{palette.text}</span>
          </div>
          <div className="mt-1 text-sm font-semibold text-slate-900">
            {event.source_node} {"->"} {event.target_node}
          </div>
          <p className="mt-2 break-words text-xs leading-5 text-slate-600">{event.payload_snippet}</p>
          <div className="mt-2 text-xs font-medium text-slate-700">action_taken: {event.action_taken}</div>
        </div>
      </div>
    </article>
  );
}

function formatTime(timestamp: number) {
  const date = new Date(timestamp * 1000);
  return date.toLocaleTimeString("zh-CN", { hour12: false });
}
