import type { AgentId, ConnectorId } from "./types";

// Single source of truth for the agent roster (docs/DIRECTION.md).
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
    model: "claude-sonnet-4-6",
    role: "fronts all input · menial work",
    color: "#3ee0ff",
  },
  {
    id: "luna",
    label: "Luna",
    model: "gpt-5.6-luna",
    role: "router · classification",
    color: "#97a5bd",
  },
  {
    id: "sol",
    label: "Sol",
    model: "gpt-5.6-sol",
    role: "planner · the mastermind",
    color: "#ffb01f",
  },
  {
    id: "executor",
    label: "Executor",
    model: "claude-opus-4-8",
    role: "complex agentic work",
    color: "#a78bff",
  },
  {
    id: "coder",
    label: "Coder",
    model: "claude-opus-4-8",
    role: "implementation",
    color: "#5a83ff",
  },
  {
    id: "reviewer",
    label: "Reviewer",
    model: "claude-opus-4-8",
    role: "independent review",
    color: "#35e39c",
  },
];

export const AGENT_META: Record<string, AgentMeta> = Object.fromEntries(
  AGENTS.map((a) => [a.id, a]),
);

export const CONNECTORS: { id: ConnectorId; label: string }[] = [
  { id: "gmail", label: "Gmail" },
  { id: "calendar", label: "Calendar" },
  { id: "notion", label: "Notion" },
  { id: "github", label: "GitHub" },
  { id: "canvas", label: "Canvas" },
  { id: "web", label: "Web" },
];

/** static delegation tree drawn faintly in the constellation */
export const HIERARCHY_EDGES: Array<[AgentId, AgentId]> = [
  ["assistant", "luna"],
  ["assistant", "sol"],
  ["assistant", "executor"],
  ["assistant", "coder"],
  ["coder", "reviewer"],
  ["sol", "executor"],
];
