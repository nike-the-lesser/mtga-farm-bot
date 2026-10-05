"""Capture Arena and plot quest-search regions; never sends game input."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vision.vision import VisionEngine, cv2
from vision.window_locator import ArenaRegionProvider
from Controller.MTGAController.quest_reroll import QuestRerollMixin


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, help="Replay a saved Arena capture instead of reading the screen")
    args = parser.parse_args()
    vision = VisionEngine()
    arena_region = None
    if args.image:
        frame = cv2.imread(str(args.image))
    else:
        provider = ArenaRegionProvider(vision=vision, assets_dir=str(ROOT / "assets" / "assert"))
        detection = provider.detect(write_debug_on_fail=False)
        if not detection.ok or detection.region is None:
            raise SystemExit(f"Arena capture unavailable: {detection.code}: {detection.message}")
        arena_region = detection.region
        vision.begin_tick()
        frame = vision.capture(arena_region)
    if frame is None:
        raise SystemExit("Arena capture returned no pixels")
    frame = cv2.resize(frame, (1920, 1080))
    cv2.imwrite(str(ROOT / "quest-search-live.png"), frame)

    # Share the bot's region without constructing a controller or starting it.
    regions = [QuestRerollMixin._QUEST_TILE_ROI]
    template = str(ROOT / "assets" / "assert" / "quest_reroll" / "gold_500.png")
    annotated = frame.copy()
    colors = [(255, 210, 0), (80, 220, 80), (255, 80, 255)]
    results = []
    for i, (region, color) in enumerate(zip(regions, colors), 1):
        x, y, w, h = region
        crop = frame[y:y+h, x:x+w]
        match = vision.find_template(crop, template, threshold=0.0)
        score = match.score if match else None
        results.append({"region": i, "bounds": list(region), "best_score": score,
                        "passes": score is not None and score >= 0.82})
        cv2.rectangle(annotated, (x, y), (x+w, y+h), color, 3)
        label = f"Region {i}: x={x}..{x+w} score={score:.3f}" if score is not None else f"Region {i}: no match"
        cv2.rectangle(annotated, (x, 665 + i*24), (x+370, 690 + i*24), (15, 15, 15), -1)
        cv2.putText(annotated, label, (x+5, 684 + i*24), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
    whole = vision.find_template(frame, template, threshold=0.82)
    if whole:
        image = cv2.imread(template)
        h, w = image.shape[:2]
        x, y = whole.x-w//2, whole.y-h//2
        cv2.rectangle(annotated, (x, y), (x+w, y+h), (0, 230, 255), 3)
    cv2.rectangle(annotated, (0, 0), (1920, 85), (15, 15, 15), -1)
    title = "SAVED CAPTURE" if args.image else "LIVE BOT VISION"
    cv2.putText(annotated, title + ": quest reroll search regions (threshold 0.82)",
                (25, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(annotated, "Colored boxes: actual search bands. Yellow box: complete 500 label found across the full image.",
                (25, 66), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
    output = ROOT / "quest-search-overlay.png"
    cv2.imwrite(str(output), annotated)
    print(json.dumps({"arena_region": arena_region, "regions": results,
                      "whole_image_score": whole.score if whole else None, "output": str(output)}, indent=2))


if __name__ == "__main__":
    main()
