export type JsonObject = Record<string, unknown>;

export type EventStatus =
  | "safe"
  | "exposed"
  | "challenged"
  | "honeypotted"
  | "infected"
  | "quarantined"
  | "isolated"
  | "recovered";

export type EventSeverity = "info" | "warning" | "critical";

export type ActionTaken =
  | "none"
  | "alert"
  | "block"
  | "quarantine"
  | "isolate"
  | "decoy"
  | "challenge"
  | "recover";

export interface AgentEvent {
  event_id: string;
  trace_id: string;
  parent_event_id?: string | null;
  timestamp: number;
  event_type: string;
  source_node: string;
  target_node: string;
  payload_snippet: string;
  status: EventStatus;
  action_taken: ActionTaken;
  severity: EventSeverity;
  monitor_level: number;
  metadata: JsonObject;
  event_category?: string | null;
  risk_tags: string[];
  trust_level: string;
  contamination_score: number;
  policy_decision?: string | null;
  policy_id?: string | null;
  edge_kind?: string | null;
  artifact_refs: string[];
}

export interface Health {
  status: string;
  service: string;
}

export interface PlatformConfig {
  llm_provider: string;
  llm_base_url: string;
  llm_model: string;
  llm_enabled: boolean;
  llm_ready: boolean;
  auth_enabled: boolean;
}

export interface AuthSession {
  auth_enabled: boolean;
  authenticated: boolean;
}

export interface StrategyRead {
  strategy_id: string;
  name: string;
  description: string;
  format: string;
  content: JsonObject;
  tags: string[];
  version: number;
  created_at: number;
  updated_at: number;
}

export interface StrategyPayload {
  name: string;
  description: string;
  format: "json";
  content: JsonObject;
  tags: string[];
}

export interface StrategyValidationIssue {
  path: string;
  message: string;
  level: "error" | "warning" | string;
}

export interface StrategyValidationResult {
  valid: boolean;
  issues: StrategyValidationIssue[];
}

export type RunStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export interface RunRead {
  run_id: string;
  strategy_id?: string | null;
  strategy_version?: number | null;
  experiment_id?: string | null;
  trace_id?: string | null;
  status: RunStatus;
  error?: string | null;
  metrics: JsonObject;
  created_at: number;
  started_at?: number | null;
  finished_at?: number | null;
}

export interface TraceSummary {
  trace_id: string;
  event_count: number;
  start_time: number;
  end_time: number;
  status_counts: Record<string, number>;
  severity_counts: Record<string, number>;
  nodes_involved: string[];
}

export interface TraceNode {
  node_id: string;
  node_type: string;
  label: string;
  contamination_score: number;
  trust_level: string;
  metadata: JsonObject;
}

export interface TraceEdge {
  edge_id: string;
  trace_id: string;
  source: string;
  target: string;
  event_id: string;
  edge_kind: string;
  timestamp: number;
  risk_tags: string[];
  contamination_delta: number;
  metadata: JsonObject;
}

export interface TraceGraphData {
  trace_id: string;
  nodes: TraceNode[];
  edges: TraceEdge[];
  metrics: JsonObject;
}

export interface ContaminationMetrics {
  trace_id: string;
  propagation_depth: number;
  blast_radius: number;
  contaminated_nodes: string[];
  first_contaminated_event_id?: string | null;
  first_detection_event_id?: string | null;
  time_to_detection_ms?: number | null;
  recovery_success: boolean;
  max_contamination_score: number;
  contamination_persistence: number;
}

export interface ContainmentStatus {
  quarantined_nodes: string[];
  isolated_tools: string[];
  blocked_edges: string[];
  revoked_memory_keys: string[];
}

export interface DefenseDecisionResponse {
  items: JsonObject[];
}

export interface Playbook {
  id: string;
  name: string;
  description: string;
}

export interface ExperimentRead {
  experiment_id: string;
  name: string;
  status: string;
  trace_id?: string | null;
  started_at?: number | null;
  completed_at?: number | null;
  error_message?: string | null;
  metrics_json?: string | null;
  config_json?: string;
  [key: string]: unknown;
}

export interface BenchmarkLevel {
  level: number | string;
  total_tested: number;
  threats_detected: number;
  false_positives: number;
  true_negatives: number;
  recall: number;
  fpr: number;
  avg_latency_ms: number;
  p95_latency_ms: number;
}

export interface BenchmarkReport {
  report_id: string;
  timestamp: number;
  pipeline_config: JsonObject;
  total_payloads: number;
  ground_truth_threats: number;
  per_level: BenchmarkLevel[];
  overall_recall: number;
  overall_fpr: number;
}

export interface ReplaySession {
  session_id: string;
  trace_id: string;
  state: "idle" | "playing" | "paused" | "stepping" | "completed";
  current_index: number;
  total_events: number;
  speed_multiplier: number;
  current_timestamp?: number | null;
  event?: AgentEvent | null;
}

export interface SettingsResponse {
  categories: Record<string, JsonObject>;
  updated_at?: number | null;
}

export interface ProvenanceNode {
  version_id: string;
  artifact_id: string;
  kind: string;
  integrity: string;
  confidentiality: string;
  scope: string;
  taint_class: "clean" | "contaminated_reachable" | "contaminated_unreachable" | string;
  state: string;
  label_enforced: boolean;
}

export interface ProvenanceResponse {
  run_id: string;
  mode: "conservative" | "tight";
  snapshot: string;
  nodes: ProvenanceNode[];
  edges: Array<{ relation_id: string; child: string; parents: string[]; relation_type: string }>;
  activities: JsonObject[];
  support_groups: JsonObject[];
  metrics: Record<string, number>;
}

export type WsStatus = "connecting" | "connected" | "disconnected";
