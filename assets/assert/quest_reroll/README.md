# Arena quest-swap references

Captured from the English Arena client on 2026-09-05 at 1280×720, Windows
display scaling 175%. Templates are normalized to the bot's 1920×1080 frame.
These are actual UI captures, not generated artwork.

- `gold_500.png`: the 500 reward and lower edge of its daily-quest circle.
- `dialog.png`: the "Confirm Swap" heading.
- `confirm.png`, `cancel.png`: retained reference captures of the enabled dialog buttons.
- `profile.png`: the inactive Profile tab, for forcing a fresh Home response.

The search excludes daily/weekly win rewards. The controller additionally checks
brightness because normalized correlation can match a disabled/dimmed control.
Home verification uses the existing `../home_anchor.png` with that same guard.
Once `dialog.png` verifies the modal, fixed normalized positions are used for
OK and Cancel: their anti-aliased border templates proved unreliable across
client window sizes in a live 1920×1080 session.
