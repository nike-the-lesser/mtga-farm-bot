"""One daily-quest replacement at session start / account login.

Only the controller's explicit landing paths call this; cache refreshes are
read-only. UI references must be captured from Arena, never synthesized.
"""
from collections import Counter
from functools import wraps
import json
import os
import threading
import time

import bot_logger
import runtime_status
from state.state_machine import BotState
from vision.vision import cv2


def serialized_home_navigation(method):
    """Keep queueing, account switching and quest dialogs on one UI owner."""
    @wraps(method)
    def guarded(self, *args, **kwargs):
        with self._home_navigation_lock:
            return method(self, *args, **kwargs)
    return guarded


def is_eligible(quest):
    try:
        gold = quest["chestDescription"]["locParams"]["number1"]
        goal = int(quest["goal"])
        progress = int(quest.get("endingProgress", 0))
        return gold in (500, "500") and goal > 0 and 0 <= progress < goal
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def _fingerprint(quest):
    # Quest ids can identify quest types rather than unique daily instances.
    # Include the objective/progress/reward so verification does not depend on
    # Arena allocating a new id for every replacement.
    return json.dumps({key: quest.get(key) for key in (
        "questId", "locKey", "goal", "endingProgress", "chestDescription",
    )}, sort_keys=True)


def replacement_verified(before, after):
    """A consumed reroll and exactly one replaced eligible quest, not completion."""
    if not after or after.get("canSwap") is not False:
        return False
    old, new = before["quests"], after["quests"]
    if len(old) != len(new):
        return False
    removed = Counter(map(_fingerprint, old)) - Counter(map(_fingerprint, new))
    added = Counter(map(_fingerprint, new)) - Counter(map(_fingerprint, old))
    return (sum(removed.values()) == sum(added.values()) == 1
            and any(is_eligible(q) and _fingerprint(q) in removed for q in old))


class QuestRerollMixin:
    _QUEST_REROLL_TIMEOUT = 10.0

    def _arm_quest_reroll(self):
        self._quest_reroll_pending = True
        self._quest_reroll_floor = self._get_log_size(self._log_path)
        self._quest_reroll_data_floor = None
        self._quest_reroll_unverified_before = None
        self._quest_reroll_dialog_open = getattr(self, "_quest_reroll_dialog_open", False)

    def _reroll_log(self, outcome, detail=""):
        bot_logger.log_info(f"Quest reroll: {outcome}" + (f" ({detail})" if detail else "") + ".")

    def _reroll_can_act(self):
        return (not self._stop_requested
                and self._get_state_from_log() not in (BotState.IN_GAME, BotState.FIND_MATCH))

    @serialized_home_navigation
    def reroll_quest_on_landing(self):
        """Return whether normal Home navigation may proceed.

        A match defers the one-shot. A failed/uncertain submission consumes it.
        A dialog whose closure cannot be verified blocks queue clicks until a
        subsequent landing check can close it (without submitting again).
        """
        if not self._reroll_can_act():
            return False
        if self._account_switch_in_progress and self._switch_owner_ident != threading.get_ident():
            return False
        if self._quest_reroll_dialog_open:
            return self._close_quest_reroll_dialog()
        if not self._quest_reroll_pending:
            return True
        self._quest_reroll_pending = False
        try:
            before = self._extract_latest_quest_snapshot(min_offset=self._quest_reroll_floor)
            if before is None:
                before = self._freshen_quest_reroll_snapshot()
            if before is None:
                self._reroll_log("stale data", "no fresh startup/login quest response")
                return True
            if before.get("canSwap") is not True:
                self._reroll_log("unavailable", "canSwap is false or unknown")
                return True
            if not any(is_eligible(q) for q in before["quests"]):
                self._reroll_log("no eligible quest")
                return True
            if not self._quest_reroll_templates_ready():
                self._reroll_log("failed", "real Arena UI references are missing")
                return True
            if (not self._reroll_can_act() or not self._navigate_to_home()
                    or not self._quest_reroll_home_visible()):
                self._reroll_log("failed", "Home not verified")
                return False
            # Re-read after navigation in case the user changed quests meanwhile.
            before = self._extract_latest_quest_snapshot(min_offset=self._quest_reroll_floor)
            if (not before or before.get("canSwap") is not True
                    or not any(is_eligible(q) for q in before["quests"])):
                self._reroll_log("unavailable", "quest state changed before opening")
                return True
            point = self._find_500_gold_quest_tile()
            if point is None:
                self._reroll_log("failed", "500-gold quest tile not recognized")
                # The log says a rerollable 500-gold quest exists, but the UI
                # could not identify it. Do not launch the queue underneath an
                # unresolved startup reroll.
                return False
            if not self._reroll_can_act():
                return False
            # Mark uncertain before the click: even a click exception can leave
            # the dialog open. No queue path may proceed until Home is verified.
            self._quest_reroll_dialog_open = True
            self._click_abs(*point, "QUEST_REROLL_OPEN")
            if not self._quest_reroll_dialog_visible():
                self._reroll_log("failed", "replacement dialog not recognized")
                return self._close_quest_reroll_dialog()
            runtime_status.set_startup_phase("Rerolling 500-gold daily quest")
            confirm = self._quest_reroll_confirm_point()
            if confirm is None or not self._reroll_can_act():
                self._reroll_log("failed", "confirmation unavailable or stopped")
                return self._close_quest_reroll_dialog()
            # This floor also protects every subsequent quest/deck read from
            # reusing the pre-click response if verification times out.
            self._quest_reroll_floor = self._get_log_size(self._log_path)
            self._quest_reroll_data_floor = self._quest_reroll_floor
            self._quest_reroll_unverified_before = before
            self._cached_quests = []
            self._cached_active_quest_id = ""
            self._cached_active_colors = ""
            self._quest_count_confirmed_fresh = False
            runtime_status.update_status(quests=[], active_quest_id="", active_quest_colors="")
            self._click_abs(*confirm, "QUEST_REROLL_CONFIRM")
            self._reroll_log("submitted")
            deadline = time.monotonic() + self._QUEST_REROLL_TIMEOUT
            refresh_at = time.monotonic() + 1.0
            reentered_home = False
            while self._reroll_can_act() and time.monotonic() < deadline:
                after = self._extract_latest_quest_snapshot(min_offset=self._quest_reroll_floor)
                if replacement_verified(before, after):
                    # The normal cache path applies the verified result and
                    # derives remaining quest count; never credit a vanished id.
                    self.refresh_quests_cache()
                    self._reroll_log("verified")
                    break
                # Live Arena updates the tile without necessarily logging a
                # QuestGetQuests response on swap. Once the dialog has closed,
                # re-enter Home once to obtain that authoritative response.
                if not reentered_home and time.monotonic() >= refresh_at:
                    reentered_home = True
                    if self._close_quest_reroll_dialog():
                        after = self._freshen_quest_reroll_snapshot(deadline=deadline)
                        if replacement_verified(before, after):
                            self.refresh_quests_cache()
                            self._reroll_log("verified")
                            break
                time.sleep(0.2)
            else:
                self._reroll_log("failed", "replacement unverified; will not submit again")
            return self._close_quest_reroll_dialog()
        except Exception as exc:
            self._reroll_log("failed", str(exc))
            if self._quest_reroll_dialog_open:
                try:
                    return self._close_quest_reroll_dialog()
                except Exception:
                    return False
            return not self._stop_requested
        finally:
            # A failed confirmation must not freeze quest reads for the rest of
            # the session. During verification a disappearing quest is rejected;
            # afterwards accept a fresh full-size list even if the click failed
            # and it is unchanged. If no such list exists, require a NEW response
            # on the next Home visit (which may legitimately follow completion
            # in a match). Never fall back to the pre-confirmation cache.
            uncertain = self._quest_reroll_unverified_before
            if uncertain is not None:
                self._quest_reroll_unverified_before = None
                try:
                    current = self._extract_latest_quest_snapshot(min_offset=self._quest_reroll_floor)
                    if current is not None and len(current["quests"]) == len(uncertain["quests"]):
                        self.refresh_quests_cache()
                    else:
                        self._quest_reroll_data_floor = self._get_log_size(self._log_path)
                except Exception as exc:
                    self._reroll_log("failed", f"cache recovery: {exc}")

    def _quest_reroll_templates_ready(self):
        return all(os.path.isfile(self._app_path("assets", "assert", "quest_reroll", name + ".png"))
                   for name in ("gold_500", "dialog", "confirm", "cancel", "profile"))

    def _freshen_quest_reroll_snapshot(self, *, deadline=None):
        """Home -> Profile -> Home makes Arena actually re-fetch the quest list.

        Measured live: clicking an already-active Home tab twice yielded no new
        response throughout the 30-second startup prime. Never relax freshness;
        make one bounded re-entry instead. This is NOT a between-match retry.
        """
        if not self._reroll_can_act() or not self._quest_reroll_templates_ready():
            return None
        if not self._quest_reroll_home_visible():
            if not self._navigate_to_home() or not self._quest_reroll_home_visible():
                return None
        profile = self._reroll_match("profile", (155, 0, 140, 150))
        if profile is None or not self._reroll_can_act():
            return None
        self._click_abs(*profile, "QUEST_REROLL_REFRESH_PROFILE")
        # Profile briefly removes the normal nav anchors during loading, so
        # allow reacquisition to settle before trying the Home click again.
        reached_home = False
        for _ in range(3):
            if deadline is not None and time.monotonic() + 4.0 >= deadline:
                break
            time.sleep(1.0)
            if not self._reroll_can_act():
                return None
            if self._navigate_to_home():
                reached_home = True
                break
        if not reached_home:
            return None
        if deadline is None:
            deadline = time.monotonic() + 8.0
        while self._reroll_can_act() and time.monotonic() < deadline:
            snapshot = self._extract_latest_quest_snapshot(min_offset=self._quest_reroll_floor)
            if snapshot is not None:
                self.refresh_quests_cache()
                return snapshot
            time.sleep(0.2)
        return None

    def _reroll_match(self, name, region, *, confidence=0.94, timeout=1.0):
        if cv2 is None:
            return None
        path = (self._app_path("assets", "assert", "home_anchor.png") if name == "home"
                else self._app_path("assets", "assert", "quest_reroll", name + ".png"))
        point = self._locate_image_center_in_scaled_arena_region(
            path, "QUEST_REROLL_" + name.upper(), rel_region=region,
            confidence=confidence, timeout=timeout, use_direct=False,
        )
        if point is None or not self._reroll_can_act():
            return None
        # NCC is invariant to dimming: the disabled OK and Home behind a modal
        # can match perfectly. Also require the captured control to be as bright
        # as its real enabled template. Always use the same 1920x1080 coordinates
        # as the scaled matcher, including on high-DPI Windows displays.
        arena = self._ensure_arena_region(force_reacquire=True)
        template = cv2.imread(path)
        if arena is None or template is None:
            return None
        self._vision.begin_tick()
        frame = self._vision.capture(arena)
        if frame is None:
            return None
        frame = cv2.resize(frame, (1920, 1080))
        x = round((point[0] - arena[0]) * 1920 / arena[2])
        y = round((point[1] - arena[1]) * 1080 / arena[3])
        h, w = template.shape[:2]
        x, y = x - w // 2, y - h // 2
        if x < 0 or y < 0:
            return None
        crop = frame[y:y+h, x:x+w]
        if crop.shape != template.shape or crop.mean() < template.mean() * 0.75:
            return None
        return point

    def _find_500_gold_quest_tile(self):
        # Measured from Arena Home at 1280x720, normalized to the existing
        # 1920x1080 frame. Each band contains one daily quest; daily/weekly win
        # rewards begin to the RIGHT of these three bands and are excluded.
        for x in (150, 450, 750):
            # The reward emblem is small and has changed slightly between Arena
            # client releases. Keep this tolerant match within only the three
            # daily-quest bands; the brightness guard still rejects dimmed UI.
            point = self._reroll_match("gold_500", (x, 750, 300, 210), confidence=0.82)
            if point is not None:
                return point
        return None

    def _quest_reroll_dialog_visible(self):
        return self._reroll_match("dialog", (760, 390, 420, 140)) is not None

    def _quest_reroll_confirm_point(self):
        """Enabled Confirm Swap centre in Arena's fixed 1920x1080 dialog.

        The live incident showed the title template correctly recognized the
        dialog but the button-border template missed at a different client size.
        The dialog itself has already been verified immediately before this is
        called, so use the stable measured centre rather than treating an
        anti-aliased border as a second safety condition.
        """
        return self._reroll_dialog_base_point((1120, 625), "QUEST_REROLL_CONFIRM_POINT")

    def _quest_reroll_home_visible(self):
        return self._reroll_match("home", (0, 0, 240, 150)) is not None

    def _close_quest_reroll_dialog(self):
        if not self._reroll_can_act():
            return False
        if self._quest_reroll_dialog_visible():
            cancel = self._reroll_dialog_base_point((800, 625), "QUEST_REROLL_CANCEL_POINT")
            if cancel is None or not self._reroll_can_act():
                self._reroll_log("failed", "dialog remains open; navigation blocked")
                return False
            self._click_abs(*cancel, "QUEST_REROLL_CANCEL")
            time.sleep(0.3)
            if self._quest_reroll_dialog_visible():
                self._reroll_log("failed", "dialog still visible after Cancel; navigation blocked")
                return False
        if not self._quest_reroll_home_visible():
            self._reroll_log("failed", "Home not visible after dialog; navigation blocked")
            return False
        self._quest_reroll_dialog_open = False
        return True

    def _reroll_dialog_base_point(self, point, label):
        """Map a measured dialog control only while the confirmed dialog owns UI."""
        if not self._reroll_can_act():
            return None
        arena = self._get_ui_action_arena_region(force_reacquire=True, label=label)
        if arena is None:
            return None
        return self._map_base_point_into_arena(arena, point)
