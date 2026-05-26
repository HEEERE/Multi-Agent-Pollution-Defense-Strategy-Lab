import { create } from "zustand";
import type { AgentEvent, ExperimentRun, NodeData, PlaybookSummary, ReplaySession, TraceSummary } from "./types";
import type { Edge, Node } from "@xyflow/react";
import { initialEdges, initialNodes, statusPalette } from "./graph";

export type AppView = "live" | "experiments" | "replay";

interface AppState {
  view: AppView;
  setView: (v: AppView) => void;

  nodes: Node<NodeData>[];
  edges: Edge[];
  setNodes: (nodes: Node<NodeData>[]) => void;
  setEdges: (edges: Edge[]) => void;
  resetTopology: () => void;
  applyEvent: (event: AgentEvent) => void;

  events: AgentEvent[];
  connected: boolean;
  setConnected: (c: boolean) => void;

  playbooks: PlaybookSummary[];
  activePlaybookId: string | null;
  setPlaybooks: (p: PlaybookSummary[]) => void;
  runPlaybook: (id: string) => Promise<void>;

  selectedNodeId: string | null;
  selectNode: (id: string | null) => void;

  traces: TraceSummary[];
  selectedTraceId: string | null;
  setTraces: (t: TraceSummary[]) => void;
  selectTrace: (id: string | null) => void;

  experiments: ExperimentRun[];
  selectedExperimentId: string | null;
  setExperiments: (e: ExperimentRun[]) => void;
  selectExperiment: (id: string | null) => void;

  replaySession: ReplaySession | null;
  setReplaySession: (s: ReplaySession | null) => void;
}

export const useStore = create<AppState>((set) => ({
  view: "live",
  setView: (v) => set({ view: v }),

  nodes: [],
  edges: [],
  setNodes: (nodes) => set({ nodes }),
  setEdges: (edges) => set({ edges }),
  resetTopology: () => set({ nodes: initialNodes, edges: initialEdges, events: [] }),
  applyEvent: (event) => {
    set((state) => ({
      events: [event, ...state.events].slice(0, 80),
      nodes: state.nodes.map((node) =>
        node.id === event.target_node
          ? { ...node, data: { ...node.data, status: event.status } }
          : node,
      ),
      edges: state.edges.map((edge) =>
        edge.source === event.source_node && edge.target === event.target_node
          ? {
              ...edge,
              animated: true,
              style: {
                ...edge.style,
                stroke: statusPalette[event.status]?.edge ?? "#22c55e",
                strokeWidth: 3,
              },
            }
          : edge,
      ),
    }));
    window.setTimeout(() => {
      set((state) => ({
        edges: state.edges.map((edge) =>
          edge.source === event.source_node && edge.target === event.target_node
            ? { ...edge, animated: false, style: { ...edge.style, strokeWidth: 2 } }
            : edge,
        ),
      }));
    }, 2600);
  },

  events: [],
  connected: false,
  setConnected: (c) => set({ connected: c }),

  playbooks: [],
  activePlaybookId: null,
  setPlaybooks: (p) => set({ playbooks: p }),
  runPlaybook: async (id) => {
    set({ activePlaybookId: id });
    try {
      await fetch(`${import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000"}/api/playbooks/${id}/run`, { method: "POST" });
    } finally {
      set({ activePlaybookId: null });
    }
  },

  selectedNodeId: null,
  selectNode: (id) => set({ selectedNodeId: id }),

  traces: [],
  selectedTraceId: null,
  setTraces: (t) => set({ traces: t }),
  selectTrace: (id) => set({ selectedTraceId: id }),

  experiments: [],
  selectedExperimentId: null,
  setExperiments: (e) => set({ experiments: e }),
  selectExperiment: (id) => set({ selectedExperimentId: id }),

  replaySession: null,
  setReplaySession: (s) => set({ replaySession: s }),
}));
