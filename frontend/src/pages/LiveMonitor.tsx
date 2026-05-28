import { useCallback, useEffect, useMemo } from "react";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  applyEdgeChanges,
  applyNodeChanges,
  type EdgeChange,
  type NodeChange,
  type NodeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { AgentNode } from "../components/AgentNode";
import { EventConsole } from "../components/EventConsole";
import { MonitorStatusPanel } from "../components/MonitorStatusPanel";
import { NodeDetailPanel } from "../components/NodeDetailPanel";
import { PlaybookPanel } from "../components/PlaybookPanel";
import { api } from "../api";
import { initialEdges, initialNodes, statusPalette } from "../graph";
import { useStore } from "../store";
import { useT } from "../i18n/context";
import type { AgentEvent, NodeData } from "../types";

const WS_URL =
  import.meta.env.VITE_WS_URL ??
  `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws/events`;

export function LiveMonitor() {
  const { t } = useT();
  const nodes = useStore((s) => s.nodes);
  const edges = useStore((s) => s.edges);
  const events = useStore((s) => s.events);
  const connected = useStore((s) => s.connected);
  const playbooks = useStore((s) => s.playbooks);
  const activePlaybookId = useStore((s) => s.activePlaybookId);
  const selectedNodeId = useStore((s) => s.selectedNodeId);

  const setNodes = useStore((s) => s.setNodes);
  const setEdges = useStore((s) => s.setEdges);
  const setConnected = useStore((s) => s.setConnected);
  const applyEvent = useStore((s) => s.applyEvent);
  const setPlaybooks = useStore((s) => s.setPlaybooks);
  const runPlaybook = useStore((s) => s.runPlaybook);
  const resetTopology = useStore((s) => s.resetTopology);
  const selectNode = useStore((s) => s.selectNode);

  const nodeTypes = useMemo<NodeTypes>(() => ({ agentNode: AgentNode }), []);

  useEffect(() => {
    if (nodes.length === 0) {
      setNodes(initialNodes);
      setEdges(initialEdges);
    }
  }, [nodes.length, setNodes, setEdges]);

  useEffect(() => {
    const socket = new WebSocket(WS_URL);
    socket.onopen = () => setConnected(true);
    socket.onclose = () => setConnected(false);
    socket.onerror = () => setConnected(false);
    socket.onmessage = (msg) => {
      try {
        applyEvent(JSON.parse(msg.data) as AgentEvent);
      } catch {
        setConnected(false);
      }
    };
    return () => socket.close();
  }, [applyEvent, setConnected]);

  useEffect(() => {
    api.getPlaybooks().then(setPlaybooks).catch(() => {});
  }, [setPlaybooks]);

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => setNodes(applyNodeChanges(changes, nodes) as typeof nodes),
    [nodes, setNodes],
  );
  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => setEdges(applyEdgeChanges(changes, edges)),
    [edges, setEdges],
  );
  const onNodeClick = useCallback(
    (_: unknown, node: { id: string }) => selectNode(node.id),
    [selectNode],
  );

  return (
    <main className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_390px] bg-slate-100 text-slate-950">
      <section className="flex min-w-0 flex-col">
        <header className="flex h-16 shrink-0 items-center justify-between border-b border-slate-200 bg-white px-6">
          <div>
            <h1 className="text-base font-semibold tracking-normal text-slate-950">
              {t("liveMonitor.title")}
            </h1>
            <p className="mt-1 text-xs text-slate-500">{t("liveMonitor.subtitle")}</p>
          </div>
          <div className="flex items-center gap-3 text-xs font-medium text-slate-600">
            <StatusLegend label={t("liveMonitor.safe")} color={statusPalette.safe.node} />
            <StatusLegend label={t("liveMonitor.challenged")} color={statusPalette.challenged.node} />
            <StatusLegend label={t("liveMonitor.infected")} color={statusPalette.infected.node} />
            <StatusLegend label={t("liveMonitor.quarantined")} color={statusPalette.quarantined.node} />
          </div>
        </header>
        <div className="relative min-h-0 flex-1">
          {playbooks.length > 0 && (
            <PlaybookPanel
              activeId={activePlaybookId}
              onReset={resetTopology}
              onRun={runPlaybook}
              playbooks={playbooks}
            />
          )}
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={onNodeClick}
            fitView
            fitViewOptions={{ padding: 0.18 }}
          >
            <Background color="#cbd5e1" gap={18} />
            <Controls position="bottom-left" />
            <MiniMap
              position="bottom-right"
              pannable
              zoomable
              nodeColor={(node) => statusPalette[(node.data as NodeData).status]?.node ?? "#16a34a"}
            />
          </ReactFlow>
          <MonitorStatusPanel events={events} />
        </div>
      </section>
      <EventConsole events={events} connected={connected} />
      {selectedNodeId && <NodeDetailPanel />}
    </main>
  );
}

function StatusLegend({ label, color }: { label: string; color: string }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span className="h-2.5 w-2.5 rounded-full" style={{ background: color }} />
      {label}
    </span>
  );
}
