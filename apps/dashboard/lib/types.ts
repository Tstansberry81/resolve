// Mirrors the control-plane domain (services/control_plane); the SSE feed in
// lib/liveEngine.ts is the only producer of this state.
// Agent roster per docs/DIRECTION.md: the assistant fronts everything.

export type AgentId =
  | "assistant"
  | "planner"
  | "executor"
  | "coder"
  | "reviewer"
  | "core";

export type ConnectorId =
  | "vault"
  | "gmail"
  | "calendar"
  | "notion"
  | "health"
  | "github"
  | "canvas"
  | "spotify"
  | "web"
  | "google"
  | "local"
  | "finance";

export type NodeId = AgentId | ConnectorId;

export type OrbState = "idle" | "listening" | "thinking" | "executing" | "waiting";

// Mirrors GoalStatus in services/control_plane/domain.py — keep the two in step.
export type GoalStatus =
  | "planning"
  | "active"
  | "waiting_approval"
  | "paused"
  | "completed"
  | "failed"
  | "cancelled";

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

/** A file on its way to the assistant. `data` is base64 WITHOUT the data: URL
 *  prefix — the control plane feeds it straight to b64decode. */
export interface Attachment {
  name: string;
  mime: string;
  data: string;
}

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
  /** "failed" = attempted and produced nothing. The dock is the source of
   *  truth for what got done, so a dead step has to be visible in it. */
  kind: "report" | "study_guide" | "pull_request" | "draft" | "audio" | "file" | "failed";
  name: string;
  meta: string;
  ts: number;
  /** clickable link to the file: GitHub blob for vault, file:// for local, web URL for cloud drives */
  href?: string;
  /** where the file lives: local | vault | gdrive | onedrive */
  location?: string;
  /** full path (tooltip / clipboard fallback for local files) */
  path?: string;
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
  laptop: "online" | "offline"; // local worker (the Mac "hands") liveness
}

export interface EngineState {
  /** "offline" = the control plane isn't answering. There is no mock mode. */
  mode: "live" | "offline";
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
  /** executor runs on the local model instead of Opus */
  localExec: boolean;
  /** a local model is configured (LOCAL_MODEL_URL set) */
  localAvailable: boolean;
  /** what each agent role ACTUALLY runs, from the control plane. The roster in
   *  lib/roster.ts only supplies a fallback — never hardcode a model name. */
  modelsByRole: Record<string, string>;
  /** today's finished morning brief — spoken once on the first armed wake */
  morningBrief: { date: string; text: string } | null;
}
