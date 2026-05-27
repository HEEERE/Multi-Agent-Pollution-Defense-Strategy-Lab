const API_URL = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const api = {
  // Platform
  getPlatformConfig: () => request<Record<string, string | boolean>>("/api/platform/config"),

  // Events
  getEvents: (params?: Record<string, string | number>) => {
    const qs = params ? "?" + new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString() : "";
    return request<import("./types").AgentEvent[]>(`/api/events${qs}`);
  },
  getEvent: (id: string) => request<import("./types").AgentEvent | null>(`/api/events/${id}`),
  getLatestEvents: (limit = 100) => request<import("./types").AgentEvent[]>(`/api/events/latest?limit=${limit}`),

  // Traces
  listTraces: (limit = 50, offset = 0) => request<import("./types").TraceSummary[]>(`/api/traces?limit=${limit}&offset=${offset}`),
  getTrace: (tid: string) => request<import("./types").AgentEvent[]>(`/api/traces/${tid}`),
  getTraceSummary: (tid: string) => request<import("./types").TraceSummary>(`/api/traces/${tid}/summary`),
  deleteTrace: (tid: string) => request<{ deleted: number; trace_id: string }>(`/api/traces/${tid}`, { method: "DELETE" }),

  // Playbooks
  getPlaybooks: () => request<import("./types").PlaybookSummary[]>("/api/playbooks"),
  runPlaybook: (id: string) => request<import("./types").AgentEvent[]>(`/api/playbooks/${id}/run`, { method: "POST" }),

  // Experiments
  createExperiment: (config: import("./types").ExperimentConfig) =>
    request<import("./types").ExperimentRun>("/api/experiments", { method: "POST", body: JSON.stringify(config) }),
  listExperiments: (limit = 50, offset = 0) => request<Record<string, unknown>[]>(`/api/experiments?limit=${limit}&offset=${offset}`),
  getExperiment: (id: string) => request<Record<string, unknown> | null>(`/api/experiments/${id}`),
  getExperimentTrace: (id: string) => request<import("./types").AgentEvent[]>(`/api/experiments/${id}/trace`),
  getExperimentMetrics: (id: string) => request<Record<string, unknown>>(`/api/experiments/${id}/metrics`),
  deleteExperiment: (id: string) => request<{ deleted: number }>(`/api/experiments/${id}`, { method: "DELETE" }),

  // Settings
  getSettings: () => request<import("./types").SettingsData>("/api/settings"),
  getSettingsCategory: (category: string) =>
    request<{ category: string; values: Record<string, unknown> }>(`/api/settings/${category}`),
  updateSettingsCategory: (category: string, values: Record<string, unknown>) =>
    request<{ status: string; category: string; updated: number }>(`/api/settings/${category}`, {
      method: "PUT",
      body: JSON.stringify(values),
    }),
  resetSettingsCategory: (category: string) =>
    request<{ category: string; values: Record<string, unknown> }>(`/api/settings/${category}/reset`, {
      method: "POST",
    }),

  // Replay
  startReplay: (traceId: string) => request<Record<string, unknown>>(`/api/replay/${traceId}/start`, { method: "POST" }),
  pauseReplay: (sid: string) => request<Record<string, unknown>>(`/api/replay/${sid}/pause`, { method: "POST" }),
  resumeReplay: (sid: string) => request<Record<string, unknown>>(`/api/replay/${sid}/resume`, { method: "POST" }),
  stepReplay: (sid: string) => request<Record<string, unknown>>(`/api/replay/${sid}/step`, { method: "POST" }),
  seekReplay: (sid: string, pos: number) => request<Record<string, unknown>>(`/api/replay/${sid}/seek?position=${pos}`, { method: "POST" }),
  speedReplay: (sid: string, mult: number) => request<Record<string, unknown>>(`/api/replay/${sid}/speed?multiplier=${mult}`, { method: "POST" }),
  getReplayState: (sid: string) => request<Record<string, unknown>>(`/api/replay/${sid}/state`),
};
