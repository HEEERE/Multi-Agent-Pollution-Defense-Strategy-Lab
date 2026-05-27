// ── Event types ──────────────────────────────────────────────

export type EventType = "input" | "communication" | "tool_call" | "intervention" | "challenge";
export type EventStatus = "safe" | "exposed" | "challenged" | "honeypotted" | "infected" | "quarantined" | "isolated" | "recovered";
export type EventSeverity = "info" | "warning" | "critical";
export type MonitorLevel = 0 | 1 | 2 | 3;
export type ActionTaken = "none" | "alert" | "block" | "quarantine" | "isolate" | "decoy";
export type ActionPolicy = "alert" | "block" | "quarantine" | "isolate";

export interface AgentEvent {
  event_id: string;
  trace_id: string;
  parent_event_id: string | null;
  timestamp: number;
  event_type: EventType;
  source_node: string;
  target_node: string;
  payload_snippet: string;
  status: EventStatus;
  action_taken: ActionTaken;
  severity: EventSeverity;
  monitor_level: MonitorLevel;
  metadata: Record<string, unknown>;
}

// ── Node / Playbook types (existing) ─────────────────────────

export interface NodeData extends Record<string, unknown> {
  label: string;
  role: string;
  status: EventStatus;
  subtitle: string;
  contamination_score?: number;
  trust_level?: string;
  risk_tags?: string[];
}

export interface PlaybookSummary {
  id: string;
  name: string;
  description: string;
}

// ── Topology config ──────────────────────────────────────────

export interface NodeConfig {
  node_id: string;
  node_type: "gateway" | "agent" | "tool" | "monitor";
  system_prompt: string;
  tools: string[];
  metadata: Record<string, unknown>;
}

export interface EdgeConfig {
  source: string;
  target: string;
  edge_type: "direct" | "monitor";
}

export type InjectionType = "prompt_injection" | "rag_poisoning" | "tool_pollution" | "cognitive_deception";

export interface InjectionConfig {
  injection_type: InjectionType;
  source_node: string;
  target_node: string;
  payload: string;
  turn: number;
  metadata: Record<string, unknown>;
}

export interface TopologyConfig {
  name: string;
  nodes: NodeConfig[];
  edges: EdgeConfig[];
  monitors: string[];
  injections: InjectionConfig[];
  max_turns: number;
  metadata: Record<string, unknown>;
}

// ── Detector config ─────────────────────────────────────────

export type DetectorType = "regex" | "rag_feature" | "semantic" | "llm_intent";

export interface DetectorConfig {
  detector_id: string;
  detector_type: DetectorType;
  enabled: boolean;
  action_policy: ActionPolicy;
  level: MonitorLevel;
  params: Record<string, unknown>;
}

export interface DetectorPipelineConfig {
  detectors: DetectorConfig[];
  short_circuit: boolean;
  log_all_detections: boolean;
  min_severity_for_llm: EventSeverity;
}

// ── Experiment config ───────────────────────────────────────

export type ExperimentStatus = "pending" | "running" | "completed" | "failed" | "stopped";

export interface ExperimentConfig {
  name: string;
  description: string;
  topology: TopologyConfig;
  detector_pipeline: DetectorPipelineConfig;
  num_runs: number;
  ground_truth: Record<string, boolean>;
  metadata: Record<string, unknown>;
}

export interface ExperimentMetrics {
  propagation_depth: number;
  time_to_detection_ms: number;
  false_positive_rate: number;
  intervention_effectiveness: number;
  detection_latency_ms: number;
  contamination_spread_rate: number;
  total_events: number;
  threats_detected: number;
  threats_blocked: number;
  cascade_depth: number;
  metadata: Record<string, unknown>;
}

export interface ExperimentRun {
  experiment_id: string;
  name: string;
  config_json: string;
  status: ExperimentStatus;
  trace_id: string | null;
  metrics: ExperimentMetrics | null;
  started_at: number | null;
  completed_at: number | null;
  error_message: string | null;
}

// ── Trace summary ───────────────────────────────────────────

export interface TraceSummary {
  trace_id: string;
  event_count: number;
  start_time: number;
  end_time: number;
  status_counts: Record<string, number>;
  severity_counts: Record<string, number>;
  nodes_involved: string[];
}

// ── Replay state ────────────────────────────────────────────

export type ReplayState = "idle" | "playing" | "paused" | "stepping" | "completed";

export interface ReplaySession {
  session_id: string;
  trace_id: string;
  state: ReplayState;
  current_index: number;
  total_events: number;
  speed_multiplier: number;
  current_timestamp: number | null;
}

// ── Settings ──────────────────────────────────────────────────

export type SettingsCategory = "detectors" | "llm" | "agents" | "system";

export interface SettingsData {
  categories: Record<SettingsCategory, Record<string, unknown>>;
  updated_at: number | null;
}

// ── TraceGraph & Contamination (v2) ───────────────────────────

export interface TraceGraphNode {
  node_id: string;
  node_type: string;
  label: string;
  contamination_score: number;
  trust_level: string;
  metadata: Record<string, unknown>;
}

export interface TraceGraphEdge {
  edge_id: string;
  trace_id: string;
  source: string;
  target: string;
  event_id: string;
  edge_kind: string;
  timestamp: number;
  risk_tags: string[];
  contamination_delta: number;
  metadata: Record<string, unknown>;
}

export interface TraceGraph {
  trace_id: string;
  nodes: TraceGraphNode[];
  edges: TraceGraphEdge[];
  metrics: Record<string, unknown>;
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

// ── Policy (v2) ───────────────────────────────────────────────

export interface PolicyRule {
  policy_id: string;
  name: string;
  description: string;
  enabled: boolean;
  priority: number;
  condition: Record<string, unknown>;
  action: string;
  severity: string;
  reason: string;
}

export interface PolicyDecision {
  policy_id: string | null;
  action: string;
  severity: string;
  reason: string;
  matched: boolean;}
