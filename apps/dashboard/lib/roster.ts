import type { AgentId, ConnectorId } from "./types";

// Agent roster: ids, labels, colors, roles (docs/DIRECTION.md).
//
// `model` here is a FALLBACK ONLY, used before the first snapshot lands or
// when the control plane is unreachable. The live value comes from
// /v1/snapshot -> state.modelsByRole. These strings drifted badly once
// (UI said Haiku while the backend ran Sonnet) — don't trust them.
// The assistant fronts every interaction; everyone else is her delegate.

export interface AgentMeta {
  id: AgentId;
  label: string;
  model: string;
  role: string;
  color: string;
}

export const AGENTS: AgentMeta[] = [
  {
    id: "assistant",
    label: "Assistant",
    model: "claude-opus-5",
    role: "fronts all input · menial work",
    color: "#3ee0ff",
  },
  {
    id: "planner",
    label: "Planner",
    model: "claude-opus-5",
    role: "planner · the mastermind",
    color: "#ffb01f",
  },
  {
    id: "executor",
    label: "Executor",
    model: "claude-sonnet-5",
    role: "complex agentic work",
    color: "#a78bff",
  },
  {
    id: "coder",
    label: "Coder",
    model: "claude-opus-5",
    role: "implementation",
    color: "#5a83ff",
  },
  {
    id: "reviewer",
    label: "Reviewer",
    model: "claude-opus-5",
    role: "independent review",
    color: "#35e39c",
  },
];

export const AGENT_META: Record<string, AgentMeta> = Object.fromEntries(
  AGENTS.map((a) => [a.id, a]),
);

export const CONNECTORS: { id: ConnectorId; label: string }[] = [
  { id: "vault", label: "Vault" },
  { id: "gmail", label: "Gmail" },
  { id: "calendar", label: "Calendar" },
  { id: "notion", label: "Notion" },
  { id: "google", label: "Google" },
  { id: "finance", label: "Finance" },
  { id: "health", label: "Health" },
  { id: "local", label: "Laptop" },
  { id: "web", label: "Web" },
];

/** static delegation tree drawn faintly in the constellation */
export const HIERARCHY_EDGES: Array<[AgentId, AgentId]> = [
  ["assistant", "planner"],
  ["assistant", "executor"],
  ["assistant", "coder"],
  ["coder", "reviewer"],
  ["planner", "executor"],
];
