import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from AI.DummyAI import DummyAI


class UnknownManaColorTest(unittest.TestCase):
    def test_unresolved_land_counts_for_generic_but_not_colored_costs(self):
        ai = DummyAI()
        debug = []
        ai._debug = debug.append
        actions = [{"action": {
            "actionType": "ActionType_Activate_Mana",
            "instanceId": 12,
            "grpId": 94178,
            "abilityGrpId": 1039,
        }}]
        with patch("AI.DummyAI.CardInfo.get_mana_color_from_ability", return_value=None), \
             patch("AI.DummyAI.CardInfo.get_land_produced_colors", return_value=set()):
            colors, total, sources = ai._get_available_mana_colors(
                actions, {12: 94178}, [{
                    "instanceId": 12,
                    "grpId": 94178,
                    "cardTypes": ["CardType_Land"],
                    "subtypes": ["SubType_Island"],
                    "zoneId": 28,
                }]
            )

        self.assertEqual(colors, set())
        self.assertEqual(total, 1)
        self.assertEqual(sources, [])
        self.assertTrue(ai._can_cast_with_mana_cost(
            [{"color": ["ManaColor_Generic"], "count": 1}], colors, total, sources
        ))
        self.assertFalse(ai._can_cast_with_mana_cost(
            [{"color": ["ManaColor_Blue"], "count": 1}], colors, total, sources
        ))
        diagnostic = next(line for line in debug if "UNRESOLVED_MANA_DIAGNOSTIC" in line)
        self.assertIn('"abilityGrpId": 1039', diagnostic)
        self.assertIn('"subtypes": ["SubType_Island"]', diagnostic)


if __name__ == "__main__":
    unittest.main()
