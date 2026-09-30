"""The opponent target scan must reach the creature row before its deadline."""
import unittest
from unittest.mock import Mock, patch

from Controller.MTGAController.Controller import Controller


class OpponentTargetScanTest(unittest.TestCase):
    def test_full_width_scan_finds_target_at_far_end_of_last_row_within_budget(self):
        controller = Controller.__new__(Controller)
        controller._Controller__live_match_id = "match"
        controller.can_execute_game_action = lambda expected_match_id=None: True
        controller.screen_bounds = ((0, 0), (4000, 2000))
        controller.patterns = {"hover_id": "hover"}
        controller.input = Mock()
        controller.log_reader = Mock()
        clock = [0.0]
        cursor = [0, 0]

        def move(x, y):
            cursor[:] = [x, y]

        controller.input.move_abs.side_effect = move
        target = (2984, 556)
        controller.log_reader.has_new_line.side_effect = lambda _: tuple(cursor) == target
        controller._Controller__parse_hover_id_line = lambda _: 316
        with patch("Controller.MTGAController.Controller.time.time", side_effect=lambda: clock[0]), \
             patch("Controller.MTGAController.Controller.time.sleep",
                   side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)), \
             patch("Controller.MTGAController.Controller.bot_logger.log_move"), \
             patch("Controller.MTGAController.Controller.bot_logger.log_click"), \
             patch("Controller.MTGAController.Controller.bot_logger.log_hover"):
            found = controller._Controller__select_object_in_region(
                316, (1444, 346), (3018, 573), 70, 1,
                "OPP_BATTLEFIELD_ITEM", max_scan_sec=8.0,
            )
        self.assertTrue(found)
        self.assertEqual(tuple(cursor), target)
        self.assertLessEqual(clock[0], 8.0)
        controller.input.left_click.assert_called_once()

    def test_scan_reaches_lower_row_and_records_a_miss(self):
        controller = Controller.__new__(Controller)
        controller.opponent_battlefield_scan_p1 = (192, 259)
        controller.opponent_battlefield_scan_p2 = (1766, 486)
        controller.battlefield_scan_step = 55
        controller._get_opponent_battlefield_scan_points_mapped = Mock(
            return_value=((1444, 346), (3018, 573))
        )
        controller._Controller__select_object_in_region = Mock(return_value=False)
        controller.input = Mock()
        controller.input.position.return_value = Mock(x=2500, y=500)
        controller._write_hand_select_debug_bundle = Mock()
        with patch("Controller.MTGAController.Controller.bot_logger.set_hover_logging"):
            self.assertFalse(controller.select_opponent_battlefield_permanent(316))

        kwargs = controller._Controller__select_object_in_region.call_args.kwargs
        self.assertEqual(kwargs["max_scan_sec"], Controller._OPPONENT_BATTLEFIELD_SCAN_TIMEOUT)
        self.assertEqual(kwargs["step"], Controller._OPPONENT_BATTLEFIELD_SCAN_STEP)
        self.assertEqual(kwargs["label"], "OPP_BATTLEFIELD_ITEM")
        self.assertEqual(
            controller._write_hand_select_debug_bundle.call_args.kwargs["reason"],
            "opponent_battlefield_select_failed",
        )


if __name__ == "__main__":
    unittest.main()
