"""Inspect quest-reroll controls, cancel the dialog, or test ONE landing reroll.

Run with the bot stopped. This tool never logs in or queues a match. --reroll
uses the normal startup freshness gate; enter Home from another tab while the
prime is waiting if Arena does not log a fresh response on the first Home click.
"""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Keep this diagnostic separate from a real bot session, including its status.
runtime_parent = (os.environ.get("MTGA_RUNTIME_DIR") or "").strip()
runtime_parent = Path(runtime_parent).expanduser() if runtime_parent else ROOT / "runtime"
os.environ["MTGA_RUNTIME_DIR"] = str(runtime_parent / "quest-reroll-validation")

from Controller.MTGAController.Controller import Controller
from Controller.MTGAController.quest_reroll import is_eligible
from vision.window_locator import focus_mtga_window


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--log-path", required=True)
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--cancel", action="store_true")
    group.add_argument("--reroll", action="store_true")
    args = ap.parse_args()
    c = Controller(args.log_path, input_backend="auto" if args.cancel or args.reroll else "null")
    focus_mtga_window()
    if args.cancel:
        c._quest_reroll_dialog_open = True
        print("Dialog closed:", c._close_quest_reroll_dialog())
    elif args.reroll:
        c.begin_session()
        print("Fresh startup quests:", c.prime_quests_for_new_session(), flush=True)
        print("Navigation may continue:", c.reroll_quest_on_landing(), flush=True)
    snapshot = c._extract_latest_quest_snapshot()
    print(json.dumps({
        "canSwap": snapshot.get("canSwap") if snapshot else None,
        "eligible": sum(is_eligible(q) for q in snapshot["quests"]) if snapshot else None,
        "home_visible": c._quest_reroll_home_visible(),
        "dialog_visible": c._quest_reroll_dialog_visible(),
        "tile": c._find_500_gold_quest_tile(),
        "confirm": c._quest_reroll_confirm_point(),
    }, indent=2))
    arena = c._ensure_arena_region(force_reacquire=True)
    if arena:
        c._vision.begin_tick()
        c._vision.save_image(c._vision.capture(arena), str(ROOT / "runtime" / "debug" / "quest-reroll-validation.png"))


if __name__ == "__main__":
    main()
