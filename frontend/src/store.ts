import { create } from "zustand";
import type { AgentEvent, ExperimentRun, NodeData, PlaybookSummary, ReplaySession, SettingsData, TraceSummary } from "./types";
import type { Edge, Node } from "@xyflow/react";
import { initialEdges, initialNodes, statusPalette } from "./graph";
import { api } from "./api";

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

  // Settings
  settings: SettingsData | null;
  settingsLoading: boolean;
  settingsSaveStatus: "idle" | "saving" | "saved" | "error";
  fetchSettings: () => Promise<void>;
  updateCategory: (category: import("./types").SettingsCategory, values: Record<string, unknown>) => Promise<boolean>;
  resetCategory: (category: import("./types").SettingsCategory) => Promise<void>;
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
    const isThreat = event.monitor_level > 0 && event.action_taken !== "none";
    const isIntervention = event.event_type === "intervention";
    const edgeClass = isIntervention ? "monitor-trail" : isThreat ? "contaminated" : undefined;

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
              className: edgeClass,
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
            ? { ...edge, animated: false, className: undefined, style: { ...edge.style, strokeWidth: 2 } }
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

  settings: null,
  settingsLoading: false,
  settingsSaveStatus: "idle",
  fetchSettings: async () => {
    set({ settingsLoading: true });
    try {
      const data = await api.getSettings();
      set({ settings: data, settingsLoading: false });
    } catch {
      set({ settingsLoading: false });
    }
  },
  updateCategory: async (category, values) => {
    set({ settingsSaveStatus: "saving" });
    try {
      await api.updateSettingsCategory(category, values);
      set((state) => {
        if (!state.settings) return { settingsSaveStatus: "saved" };
        const categories = { ...state.settings.categories, [category]: { ...state.settings.categories[category], ...values } };
        return { settings: { ...state.settings, categories }, settingsSaveStatus: "saved" };
      });
      return true;
    } catch {
      set({ settingsSaveStatus: "error" });
      return false;
    }
  },
  resetCategory: async (category) => {
    set({ settingsSaveStatus: "saving" });
    try {
      const result = await api.resetSettingsCategory(category);
      set((state) => {
        if (!state.settings) return { settingsSaveStatus: "saved" };
        const categories = { ...state.settings.categories, [category]: result.values };
        return { settings: { ...state.settings, categories }, settingsSaveStatus: "saved" };
      });
    } catch {
      set({ settingsSaveStatus: "error" });
    }
  },
}));
