import axios, { AxiosError, type AxiosRequestConfig } from "axios";
import type {
  AgentEvent,
  AuthSession,
  BenchmarkReport,
  ContainmentStatus,
  DefenseDecisionResponse,
  ExperimentRead,
  Health,
  JsonObject,
  PlatformConfig,
  Playbook,
  ReplaySession,
  RunRead,
  SettingsResponse,
  StrategyPayload,
  StrategyRead,
  StrategyValidationResult,
  TraceGraphData,
  TraceSummary,
  ContaminationMetrics,
} from "./types";

const client = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? "",
  timeout: 60_000,
  headers: { "Content-Type": "application/json" },
  withCredentials: true,
});

async function request<T>(config: AxiosRequestConfig): Promise<T> {
  try {
    const response = await client.request<T>(config);
    return response.data;
  } catch (error) {
    const axiosError = error as AxiosError<{ detail?: string; message?: string }>;
    const detail =
      axiosError.response?.data?.detail ??
      axiosError.response?.data?.message ??
      axiosError.message;
    throw new Error(detail || "请求失败");
  }
}

export const api = {
  getAuthSession: () => request<AuthSession>({ url: "/api/auth/session" }),
  createAuthSession: (apiKey: string) =>
    request<AuthSession>({
      url: "/api/auth/session",
      method: "POST",
      data: { api_key: apiKey },
    }),
  deleteAuthSession: () =>
    request<AuthSession>({ url: "/api/auth/session", method: "DELETE" }),
  getHealth: () => request<Health>({ url: "/health" }),
  getPlatformConfig: () =>
    request<PlatformConfig>({ url: "/api/platform/config" }),
  getLatestEvents: (limit = 20) =>
    request<AgentEvent[]>({
      url: "/api/v1/events/latest",
      params: { limit },
    }),
  queryEvents: (params: Record<string, string | number | undefined>) =>
    request<AgentEvent[]>({ url: "/api/v1/events", params }),

  listTraces: () => request<TraceSummary[]>({ url: "/api/v1/traces" }),
  getTrace: (traceId: string) =>
    request<AgentEvent[]>({ url: `/api/v1/traces/${traceId}` }),
  getTraceSummary: (traceId: string) =>
    request<TraceSummary>({ url: `/api/v1/traces/${traceId}/summary` }),
  getTraceGraph: (traceId: string) =>
    request<TraceGraphData>({ url: `/api/v1/traces/${traceId}/graph` }),
  getTraceContamination: (traceId: string) =>
    request<ContaminationMetrics>({
      url: `/api/v1/traces/${traceId}/contamination`,
    }),
  deleteTrace: (traceId: string) =>
    request<{ deleted: number }>({
      url: `/api/v1/traces/${traceId}`,
      method: "DELETE",
    }),

  listStrategies: () =>
    request<StrategyRead[]>({ url: "/api/v1/strategies" }),
  getStrategy: (strategyId: string) =>
    request<StrategyRead>({ url: `/api/v1/strategies/${strategyId}` }),
  validateStrategy: (content: JsonObject) =>
    request<StrategyValidationResult>({
      url: "/api/v1/strategies/validate",
      method: "POST",
      data: { content },
    }),
  createStrategy: (payload: StrategyPayload) =>
    request<StrategyRead>({
      url: "/api/v1/strategies",
      method: "POST",
      data: payload,
    }),
  updateStrategy: (strategyId: string, payload: Partial<StrategyPayload>) =>
    request<StrategyRead>({
      url: `/api/v1/strategies/${strategyId}`,
      method: "PUT",
      data: payload,
    }),
  deleteStrategy: (strategyId: string) =>
    request<{ deleted: number }>({
      url: `/api/v1/strategies/${strategyId}`,
      method: "DELETE",
    }),
  runStrategy: (strategyId: string) =>
    request<{ run_id: string; status: string }>({
      url: `/api/v1/strategies/${strategyId}/run`,
      method: "POST",
    }),

  getRun: (runId: string) =>
    request<RunRead>({ url: `/api/v1/runs/${runId}` }),
  getRunEvents: (runId: string) =>
    request<AgentEvent[]>({ url: `/api/v1/runs/${runId}/events` }),
  getRunMetrics: (runId: string) =>
    request<JsonObject>({ url: `/api/v1/runs/${runId}/metrics` }),
  cancelRun: (runId: string) =>
    request<JsonObject>({
      url: `/api/v1/runs/${runId}/cancel`,
      method: "POST",
    }),

  listPlaybooks: () =>
    request<Playbook[]>({ url: "/api/v1/playbooks" }),
  runPlaybook: (id: string, delaySeconds = 0.15) =>
    request<AgentEvent[]>({
      url: `/api/v1/playbooks/${id}/run`,
      method: "POST",
      params: { delay_seconds: delaySeconds },
    }),

  listExperiments: () =>
    request<ExperimentRead[]>({ url: "/api/v1/experiments" }),
  createExperiment: (config: JsonObject) =>
    request<ExperimentRead>({
      url: "/api/v1/experiments",
      method: "POST",
      data: config,
      timeout: 120_000,
    }),
  getExperiment: (id: string) =>
    request<ExperimentRead>({ url: `/api/v1/experiments/${id}` }),
  getExperimentTrace: (id: string) =>
    request<AgentEvent[]>({ url: `/api/v1/experiments/${id}/trace` }),
  getExperimentMetrics: (id: string) =>
    request<JsonObject>({ url: `/api/v1/experiments/${id}/metrics` }),
  deleteExperiment: (id: string) =>
    request<{ deleted: number }>({
      url: `/api/v1/experiments/${id}`,
      method: "DELETE",
    }),

  startReplay: (traceId: string) =>
    request<ReplaySession>({
      url: `/api/v1/replay/${traceId}/start`,
      method: "POST",
    }),
  pauseReplay: (sessionId: string) =>
    request<ReplaySession>({
      url: `/api/v1/replay/${sessionId}/pause`,
      method: "POST",
    }),
  resumeReplay: (sessionId: string) =>
    request<ReplaySession>({
      url: `/api/v1/replay/${sessionId}/resume`,
      method: "POST",
    }),
  stepReplay: (sessionId: string) =>
    request<ReplaySession>({
      url: `/api/v1/replay/${sessionId}/step`,
      method: "POST",
    }),
  seekReplay: (sessionId: string, position: number) =>
    request<ReplaySession>({
      url: `/api/v1/replay/${sessionId}/seek`,
      method: "POST",
      params: { position },
    }),
  speedReplay: (sessionId: string, multiplier: number) =>
    request<ReplaySession>({
      url: `/api/v1/replay/${sessionId}/speed`,
      method: "POST",
      params: { multiplier },
    }),
  getReplayState: (sessionId: string) =>
    request<ReplaySession>({ url: `/api/v1/replay/${sessionId}/state` }),

  runBenchmark: () =>
    request<BenchmarkReport>({
      url: "/api/v1/benchmark/run",
      method: "POST",
      timeout: 180_000,
    }),
  listBenchmarkReports: () =>
    request<BenchmarkReport[]>({ url: "/api/v1/benchmark/reports" }),
  getBenchmarkReport: (id: string) =>
    request<BenchmarkReport>({
      url: `/api/v1/benchmark/reports/${id}`,
    }),

  getDefenseMemory: () =>
    request<JsonObject>({ url: "/api/v1/defense/memory" }),
  getDefenseDecisions: () =>
    request<DefenseDecisionResponse>({
      url: "/api/v1/defense/decisions/latest",
    }),
  getContainmentStatus: () =>
    request<ContainmentStatus>({
      url: "/api/v1/defense/containment/status",
    }),
  releaseNode: (nodeId: string) =>
    request<JsonObject>({
      url: `/api/v1/defense/containment/release/node/${encodeURIComponent(nodeId)}`,
      method: "POST",
    }),
  releaseTool: (toolId: string) =>
    request<JsonObject>({
      url: `/api/v1/defense/containment/release/tool/${encodeURIComponent(toolId)}`,
      method: "POST",
    }),
  releaseEdge: (source: string, target: string) =>
    request<JsonObject>({
      url: "/api/v1/defense/containment/release/edge",
      method: "POST",
      params: { source, target },
    }),
  releaseMemoryKey: (key: string) =>
    request<JsonObject>({
      url: `/api/v1/defense/containment/release/memory/${encodeURIComponent(key)}`,
      method: "POST",
    }),
  checkRecovery: (nodeId: string) =>
    request<JsonObject>({
      url: `/api/v1/defense/recovery/check/${encodeURIComponent(nodeId)}`,
      method: "POST",
    }),
  approveRecovery: (nodeId: string) =>
    request<JsonObject>({
      url: `/api/v1/defense/recovery/approve/${encodeURIComponent(nodeId)}`,
      method: "POST",
    }),

  getSettings: () =>
    request<SettingsResponse>({ url: "/api/v1/settings" }),
  getSettingsCategory: (category: string) =>
    request<{ category: string; values: JsonObject }>({
      url: `/api/v1/settings/${category}`,
    }),
  updateSettingsCategory: (category: string, payload: JsonObject) =>
    request<JsonObject>({
      url: `/api/v1/settings/${category}`,
      method: "PUT",
      data: payload,
    }),
  resetSettingsCategory: (category: string) =>
    request<{ category: string; values: JsonObject }>({
      url: `/api/v1/settings/${category}/reset`,
      method: "POST",
    }),
};
