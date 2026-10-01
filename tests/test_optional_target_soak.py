"""Temporary optional-target soak writes evidence without real screen access."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from Controller.MTGAController.Controller import Controller


class OptionalTargetSoakTest(unittest.TestCase):
    def test_before_and_after_share_bundle_with_state_and_mocked_screenshots(self):
        c = Controller.__new__(Controller)
        c._current_account_screen_name = "test-account"
        c._arena_region = (100, 100, 1920, 1080)
        c._Controller__pending_target_select = {
            "source_id": 303, "token": 4,
            "groups": [{"min": 1, "selected": 1}, {"min": 0, "selected": 0}],
        }
        c.updated_game_state = Mock()
        c.updated_game_state.get_turn_info.return_value = {"decisionPlayer": 2}
        c._vision = Mock()
        c._vision.save_image.side_effect = lambda image, path: Path(path).write_bytes(b"mock screenshot")
        with tempfile.TemporaryDirectory() as directory, \
                patch("Controller.MTGAController.Controller.bot_logger.ensure_debug_dir", return_value=directory), \
                patch("Controller.MTGAController.Controller.runtime_status.read_status", return_value={"session_id": "session"}):
            bundle = c._Controller__write_optional_target_soak(
                "zero_before_click", match_id="match", token=4, point=(1500, 900))
            c._Controller__pending_target_select = None
            c._Controller__write_optional_target_soak(
                "zero_acknowledged", match_id="match", token=4, bundle_dir=bundle)
            before = json.loads((Path(directory) / "zero_before_click.json").read_text())
            after = json.loads((Path(directory) / "zero_acknowledged.json").read_text())
            self.assertTrue(before["temporary_soak"])
            self.assertEqual(before["session_id"], "session")
            self.assertEqual(before["match_id"], "match")
            self.assertEqual(before["account"], "test-account")
            self.assertEqual(before["button_point"], [1500, 900])
            self.assertEqual(before["submit_zero_confidence"], 0.85)
            self.assertEqual(before["pending_target_select"]["groups"][1]["selected"], 0)
            self.assertEqual(after["pending_target_select"], {})
            self.assertTrue((Path(directory) / "zero_before_click.jpg").exists())
            self.assertTrue((Path(directory) / "zero_acknowledged.jpg").exists())
            self.assertEqual(c._vision.capture.call_count, 2)

    def test_capture_failure_is_diagnostic_only(self):
        c = Controller.__new__(Controller)
        c._Controller__pending_target_select = None
        c.updated_game_state = Mock()
        c.updated_game_state.get_turn_info.return_value = {}
        c._vision = Mock()
        c._vision.capture.side_effect = RuntimeError("capture unavailable")
        with tempfile.TemporaryDirectory() as directory, \
                patch("Controller.MTGAController.Controller.bot_logger.ensure_debug_dir", return_value=directory), \
                patch("Controller.MTGAController.Controller.runtime_status.read_status", return_value={}), \
                patch("Controller.MTGAController.Controller.bot_logger.log_error") as errors:
            self.assertEqual(c._Controller__write_optional_target_soak(
                "equipment_before_scan", match_id="match", token=4), directory)
            self.assertTrue((Path(directory) / "equipment_before_scan.json").exists())
            self.assertIn("OPTIONAL_TARGET_SOAK_FAILED", errors.call_args.args[0])

    def test_audit_index_recognizes_soak_and_persistent_outcomes(self):
        path = Path(__file__).resolve().parents[1] / ".agents/skills/audit-logs/scripts/summarize.py"
        spec = importlib.util.spec_from_file_location("optional_target_audit", path)
        audit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(audit)
        lines = [
            "[2026-10-01 12:00:00.000] [INFO] FIERY_EQUIPMENT_ATTEMPT: target=287 found=True",
            "[2026-10-01 12:00:01.000] [INFO] OPTIONAL_TARGET_SOAK: event=equipment_acknowledged bundle=example",
            "[2026-10-01 12:00:02.000] [ERROR] OPTIONAL_TARGET_SOAK_FAILED: capture failed",
            "[2026-10-01 12:00:03.000] [INFO] SUBMIT_ZERO_ATTEMPT: source=303",
            "[2026-10-01 12:00:04.000] [INFO] SUBMIT_ZERO_ACKNOWLEDGED: prompt advanced",
        ]
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            (runtime / "analysis").mkdir()
            (runtime / "analysis/history.log").write_text("\n".join(lines), encoding="utf-8")
            events, coverage = audit.history_events(runtime, audit.timestamp(lines[0]), audit.timestamp(lines[-1]))
            self.assertEqual([e["kind"] for e in events], [
                "FIERY_EQUIPMENT_ATTEMPT", "OPTIONAL_TARGET_SOAK", "OPTIONAL_TARGET_SOAK_FAILED",
                "SUBMIT_ZERO_ATTEMPT", "SUBMIT_ZERO_ACKNOWLEDGED"])
            self.assertEqual(events[1]["line"], 2)
            self.assertTrue(coverage)
            # Ordinary attempt/outcome logs remain useful when soak is removed.
            (runtime / "analysis/history.log").write_text("\n".join([lines[0], *lines[3:]]), encoding="utf-8")
            events, _ = audit.history_events(runtime, audit.timestamp(lines[0]), audit.timestamp(lines[-1]))
            self.assertEqual(len(events), 3)


if __name__ == "__main__":
    unittest.main()
