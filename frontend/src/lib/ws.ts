import type { AgentEvent } from "./types";

type MessageHandler = (message: AgentEvent | unknown) => void;
type StatusHandler = (connected: boolean) => void;

function wsBaseUrl() {
  if (import.meta.env.VITE_WS_BASE_URL) {
    return import.meta.env.VITE_WS_BASE_URL.replace(/\/$/, "");
  }
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}`;
}

function connect(path: string, onMessage: MessageHandler, onStatus?: StatusHandler) {
  let socket: WebSocket | null = null;
  let closed = false;
  let retryTimer: number | null = null;

  const open = () => {
    if (closed) return;
    socket = new WebSocket(`${wsBaseUrl()}${path}`);
    socket.addEventListener("open", () => onStatus?.(true));
    socket.addEventListener("message", (event) => {
      try {
        onMessage(JSON.parse(event.data));
      } catch {
        onMessage(event.data);
      }
    });
    socket.addEventListener("close", () => {
      onStatus?.(false);
      if (!closed) retryTimer = window.setTimeout(open, 2_000);
    });
    socket.addEventListener("error", () => socket?.close());
  };

  open();
  return () => {
    closed = true;
    if (retryTimer) window.clearTimeout(retryTimer);
    socket?.close();
  };
}

export function connectGlobalEvents(
  onEvent: MessageHandler,
  onStatus?: StatusHandler,
) {
  return connect("/ws/events", onEvent, onStatus);
}

export function connectRunEvents(
  runId: string,
  onEvent: MessageHandler,
  onStatus?: StatusHandler,
) {
  return connect(`/ws/runs/${runId}`, onEvent, onStatus);
}

export function isAgentEvent(value: unknown): value is AgentEvent {
  if (!value || typeof value !== "object") return false;
  const item = value as Partial<AgentEvent>;
  return Boolean(item.event_id && item.trace_id && item.source_node);
}
