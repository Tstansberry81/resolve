from pathlib import Path
import unittest

from resolve_control_plane.config import model_choice
from resolve_control_plane.domain import (
    AutonomyMode,
    GoalStatus,
    GOAL_TRANSITIONS,
    assert_transition,
)
from resolve_control_plane.policy import PolicyDecision, evaluate_tool_call


CONFIG = Path(__file__).resolve().parents[3] / "config"


class ControlPlaneTests(unittest.TestCase):
    def test_goal_transition_rejects_terminal_restart(self):
        with self.assertRaises(ValueError):
            assert_transition(GoalStatus.COMPLETED, GoalStatus.ACTIVE, GOAL_TRANSITIONS)

    def test_email_send_always_requires_approval(self):
        result = evaluate_tool_call("email.send", AutonomyMode.AUTOPILOT, config_dir=CONFIG)
        self.assertEqual(result.decision, PolicyDecision.REQUIRE_APPROVAL)

    def test_email_send_in_execute_mode_surfaces_approval_not_deny(self):
        result = evaluate_tool_call("email.send", AutonomyMode.EXECUTE, config_dir=CONFIG)
        self.assertEqual(result.decision, PolicyDecision.REQUIRE_APPROVAL)

    def test_email_send_denied_below_execute_mode(self):
        result = evaluate_tool_call("email.send", AutonomyMode.ASSIST, config_dir=CONFIG)
        self.assertEqual(result.decision, PolicyDecision.DENY)

    def test_unknown_tool_is_denied(self):
        result = evaluate_tool_call("shrug.unknown", AutonomyMode.AUTOPILOT, config_dir=CONFIG)
        self.assertEqual(result.decision, PolicyDecision.DENY)

    def test_secret_read_requires_autopilot(self):
        result = evaluate_tool_call("secret.read", AutonomyMode.EXECUTE, config_dir=CONFIG)
        self.assertEqual(result.decision, PolicyDecision.DENY)

    def test_read_is_allowed_in_observe_mode(self):
        result = evaluate_tool_call("finance.read", AutonomyMode.OBSERVE, config_dir=CONFIG)
        self.assertEqual(result.decision, PolicyDecision.ALLOW)

    def test_model_route_is_config_driven(self):
        route = model_choice("coding_implementer", config_dir=CONFIG)
        self.assertEqual(route.provider, "openai")
        self.assertEqual(route.reasoning, "high")


if __name__ == "__main__":
    unittest.main()
