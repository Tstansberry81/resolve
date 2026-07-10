// Mirrors the control-plane domain (services/control_plane) so the real SSE
// feed can replace the mock engine without touching components.
// Agent roster per docs/DIRECTION.md: the assistant fronts everything.

export type AgentId =
  | "assistant"
  | "luna"
  | "sol"
  | "executor"
  | "coder"
  | "reviewer"
  | "core";

export type ConnectorId =
  | "gmail"
  | "calendar"
  | "notion"
  | "github"
  | "canvas"
  | "web";

export type NodeId = AgentId | ConnectorId;

export type OrbState = "idle" | "listening" | "thinking" | "executing" | "waiting";

export type GoalStatus =
  | "planning"
  | "active"
  | "waiting_approval"
  | "paused"
  | "completed"
  | "failed";

export type RiskClass =
  | "read"
  | "draft"
  | "reversible_write"
  | "bounded_external_write"
  | "communication_send"
  | "destructive"
  | "financial";

export interface Goal {
  id: string;
  objective: string;
  category: "school" | "email" | "coding" | "research" | "personal";
  status: GoalStatus;
  autonomyMode: "observe" | "assist" | "execute" | "autopilot";
  progress: number; // 0..1
  budgetUsd: number;
  spentUsd: number;
  deadline: string | null;
  nextAction: string;
  blocker: string | null;
}

export type EventLevel = "info" | "success" | "warn" | "error" | "approval";

export interface AgentEvent {
  id: number;
  ts: number; // epoch ms
  goalId: string | null;
  type: string; // e.g. task.started, tool.call, verify.passed
  actor: NodeId;
  summary: string;
  detail: string | null;
  level: EventLevel;
  /** constellation edge to light up */
  edge: { from: NodeId; to: NodeId } | null;
}

export interface Approval {
  id: string;
  goalId: string;
  actionSummary: string;
  risk: RiskClass;
  preview: string[];
  recipient: string | null;
  undoWindow: string | null;
  status: "pending" | "approved" | "rejected" | "expired";
}

export interface Artifact {
  id: string;
  goalId: string;
  kind: "report" | "study_guide" | "pull_request" | "draft" | "audio" | "file";
  name: string;
  meta: string;
  ts: number;
}

export interface ConnectorHealth {
  id: ConnectorId;
  label: string;
  status: "healthy" | "degraded" | "down";
  latencyMs: number;
}

export interface ModelLane {
  role: string;
  model: string;
  p50Ms: number;
  costTodayUsd: number;
}

export interface Vitals {
  connectors: ConnectorHealth[];
  models: ModelLane[];
  queueDepth: number;
  errorRate: number; // 0..1
  tokensToday: number;
  costTodayUsd: number;
  workerStatus: "idle" | "executing" | "stopped";
}

export interface EngineState {
  orb: OrbState;
  orbCaption: string;
  goals: Goal[];
  events: AgentEvent[];
  approvals: Approval[];
  artifacts: Artifact[];
  vitals: Vitals;
  /** node ids currently active, for the constellation */
  activeNodes: NodeId[];
  activeEdge: { from: NodeId; to: NodeId } | null;
  emergencyStopped: boolean;
}
