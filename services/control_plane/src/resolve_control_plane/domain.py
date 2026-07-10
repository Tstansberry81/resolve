from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class AutonomyMode(StrEnum):
    OBSERVE = "observe"
    ASSIST = "assist"
    EXECUTE = "execute"
    AUTOPILOT = "autopilot"


class GoalStatus(StrEnum):
    DRAFT = "draft"
    PLANNING = "planning"
    ACTIVE = "active"
    WAITING_APPROVAL = "waiting_approval"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(StrEnum):
    BLOCKED = "blocked"
    READY = "ready"
    CLAIMED = "claimed"
    RUNNING = "running"
    VERIFYING = "verifying"
    WAITING_APPROVAL = "waiting_approval"
    RETRY_SCHEDULED = "retry_scheduled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RiskClass(StrEnum):
    READ = "read"
    DRAFT = "draft"
    SIMULATE = "simulate"
    REVERSIBLE_WRITE = "reversible_write"
    BOUNDED_EXTERNAL_WRITE = "bounded_external_write"
    COMMUNICATION_SEND = "communication_send"
    DESTRUCTIVE = "destructive"
    FINANCIAL = "financial"
    CREDENTIAL_OR_PERMISSION = "credential_or_permission"


GOAL_TRANSITIONS: dict[GoalStatus, set[GoalStatus]] = {
    GoalStatus.DRAFT: {GoalStatus.PLANNING, GoalStatus.CANCELLED},
    GoalStatus.PLANNING: {GoalStatus.ACTIVE, GoalStatus.FAILED, GoalStatus.CANCELLED},
    GoalStatus.ACTIVE: {
        GoalStatus.WAITING_APPROVAL,
        GoalStatus.PAUSED,
        GoalStatus.COMPLETED,
        GoalStatus.FAILED,
        GoalStatus.CANCELLED,
    },
    GoalStatus.WAITING_APPROVAL: {
        GoalStatus.ACTIVE,
        GoalStatus.PAUSED,
        GoalStatus.FAILED,
        GoalStatus.CANCELLED,
    },
    GoalStatus.PAUSED: {GoalStatus.ACTIVE, GoalStatus.CANCELLED},
    GoalStatus.COMPLETED: set(),
    GoalStatus.FAILED: {GoalStatus.PLANNING, GoalStatus.CANCELLED},
    GoalStatus.CANCELLED: set(),
}


TASK_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.BLOCKED: {TaskStatus.READY, TaskStatus.CANCELLED},
    TaskStatus.READY: {TaskStatus.CLAIMED, TaskStatus.CANCELLED},
    TaskStatus.CLAIMED: {TaskStatus.RUNNING, TaskStatus.READY, TaskStatus.FAILED},
    TaskStatus.RUNNING: {
        TaskStatus.VERIFYING,
        TaskStatus.WAITING_APPROVAL,
        TaskStatus.RETRY_SCHEDULED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    },
    TaskStatus.VERIFYING: {
        TaskStatus.SUCCEEDED,
        TaskStatus.RETRY_SCHEDULED,
        TaskStatus.FAILED,
    },
    TaskStatus.WAITING_APPROVAL: {
        TaskStatus.READY,
        TaskStatus.SUCCEEDED,
        TaskStatus.CANCELLED,
        TaskStatus.FAILED,
    },
    TaskStatus.RETRY_SCHEDULED: {TaskStatus.READY, TaskStatus.CANCELLED},
    TaskStatus.SUCCEEDED: set(),
    TaskStatus.FAILED: {TaskStatus.READY, TaskStatus.CANCELLED},
    TaskStatus.CANCELLED: set(),
}


def assert_transition(current: StrEnum, target: StrEnum, transitions: dict) -> None:
    if target not in transitions[current]:
        raise ValueError(f"invalid transition: {current} -> {target}")


@dataclass(frozen=True)
class SuccessCriterion:
    description: str
    verifier: str
    required: bool = True


@dataclass
class GoalSpec:
    objective: str
    category: str
    autonomy_mode: AutonomyMode = AutonomyMode.ASSIST
    success_criteria: list[SuccessCriterion] = field(default_factory=list)
    constraints: dict[str, Any] = field(default_factory=dict)
    allowed_connectors: list[str] = field(default_factory=list)
    deadline: datetime | None = None
    max_cost_usd: float = 5.0
    max_runtime_minutes: int = 60
    max_replans: int = 2

    def validate(self) -> None:
        if not self.objective.strip():
            raise ValueError("goal objective is required")
        if not self.success_criteria:
            raise ValueError("at least one success criterion is required")
        if self.max_cost_usd <= 0 or self.max_runtime_minutes <= 0:
            raise ValueError("goal budgets must be positive")


@dataclass
class TaskSpec:
    title: str
    kind: str
    model_role: str
    risk: RiskClass
    success_criteria: list[SuccessCriterion]
    connector: str | None = None
    tool: str | None = None
    input: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    max_attempts: int = 3
