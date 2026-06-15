import { useEffect } from "react";
import { Outlet } from "react-router-dom";
import { connectGlobalEvents, isAgentEvent } from "../../lib/ws";
import { useAppStore } from "../../store/app-store";
import { ToastViewport } from "../common/ToastViewport";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

export function AppShell() {
  const addLiveEvent = useAppStore((state) => state.addLiveEvent);
  const setWsStatus = useAppStore((state) => state.setWsStatus);

  useEffect(
    () =>
      connectGlobalEvents(
        (message) => {
          if (isAgentEvent(message)) addLiveEvent(message);
        },
        (connected) => setWsStatus(connected ? "connected" : "disconnected"),
      ),
    [addLiveEvent, setWsStatus],
  );

  return (
    <div className="min-h-screen bg-ink-950 text-slate-100">
      <Sidebar />
      <Topbar />
      <main className="fixed bottom-0 left-[var(--sidebar-width)] right-0 top-[var(--topbar-height)] overflow-auto bg-[radial-gradient(circle_at_60%_0%,rgba(0,174,234,0.045),transparent_30%)]">
        <Outlet />
      </main>
      <ToastViewport />
    </div>
  );
}
