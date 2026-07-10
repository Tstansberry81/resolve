from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .config import load_json
from .domain import AutonomyMode, RiskClass


class PolicyDecision(StrEnum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


MODE_ORDER = {
    AutonomyMode.OBSERVE: 0,
    AutonomyMode.ASSIST: 1,
    AutonomyMode.EXECUTE: 2,
    AutonomyMode.AUTOPILOT: 3,
}


@dataclass(frozen=True)
class PolicyResult:
    decision: PolicyDecision
    risk: RiskClass
    reason: str


def evaluate_tool_call(
    tool_name: str,
    autonomy_mode: AutonomyMode,
    *,
    ambiguous: bool = False,
    config_dir: Path | None = None,
) -> PolicyResult:
    config = load_json("tool_policies.json", config_dir)
    override = config["overrides"].get(tool_name)
    if not override:
        return PolicyResult(PolicyDecision.DENY, RiskClass.CREDENTIAL_OR_PERMISSION, "unknown tool")

    risk = RiskClass(override["risk"])
    rule = config["risk_classes"][risk.value]
    minimum = AutonomyMode(rule["minimum_mode"])
    if MODE_ORDER[autonomy_mode] < MODE_ORDER[minimum]:
        return PolicyResult(
            PolicyDecision.DENY,
            risk,
            f"{autonomy_mode} mode does not permit {risk}",
        )

    approval = rule["approval"]
    if approval == "always" or (approval == "on_ambiguity" and ambiguous):
        return PolicyResult(PolicyDecision.REQUIRE_APPROVAL, risk, "human approval required")
    return PolicyResult(PolicyDecision.ALLOW, risk, "allowed by policy")
