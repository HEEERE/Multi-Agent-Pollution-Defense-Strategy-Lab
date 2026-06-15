import { create } from "zustand";
import type { AgentEvent, WsStatus } from "../lib/types";

interface Toast {
  id: number;
  title: string;
  kind: "success" | "error" | "info";
}

interface AppState {
  wsStatus: WsStatus;
  liveEvents: AgentEvent[];
  toasts: Toast[];
  setWsStatus: (status: WsStatus) => void;
  addLiveEvent: (event: AgentEvent) => void;
  seedLiveEvents: (events: AgentEvent[]) => void;
  addToast: (title: string, kind?: Toast["kind"]) => void;
  dismissToast: (id: number) => void;
}

let toastId = 0;

export const useAppStore = create<AppState>((set) => ({
  wsStatus: "connecting",
  liveEvents: [],
  toasts: [],
  setWsStatus: (wsStatus) => set({ wsStatus }),
  addLiveEvent: (event) =>
    set((state) => ({
      liveEvents: [
        event,
        ...state.liveEvents.filter((item) => item.event_id !== event.event_id),
      ].slice(0, 200),
    })),
  seedLiveEvents: (events) =>
    set((state) => ({
      liveEvents: [
        ...state.liveEvents,
        ...events.filter(
          (event) =>
            !state.liveEvents.some((item) => item.event_id === event.event_id),
        ),
      ]
        .sort((a, b) => b.timestamp - a.timestamp)
        .slice(0, 200),
    })),
  addToast: (title, kind = "info") => {
    const id = ++toastId;
    set((state) => ({ toasts: [...state.toasts, { id, title, kind }] }));
    window.setTimeout(
      () =>
        set((state) => ({
          toasts: state.toasts.filter((toast) => toast.id !== id),
        })),
      3_500,
    );
  },
  dismissToast: (id) =>
    set((state) => ({
      toasts: state.toasts.filter((toast) => toast.id !== id),
    })),
}));
