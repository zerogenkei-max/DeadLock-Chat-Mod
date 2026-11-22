# Validation

What has been tested and what hasn't. "Mock" means the Node tests run the mod's
script against fake Panorama panels; that isn't the same as playing the game.
This file is in the Source ZIP only, not the Mod ZIP.

## 0.2.4

Compatibility, 13 November 2026: the three replaced layouts (chat, settings
popup, dashboard footer bar) were checked on Deadlock 6861 / Steam 26546669.
They are byte-identical to the baseline the mod was built against (6821 /
Steam 26224525). The chat stylesheet is unchanged too.

Automated tests added or extended for:

- Messages and pings in the hideout showing again.
- Theme import changing only look and filter settings.
- Timer steps (1 s up to 10 s, then 5 s) and the 0 s and 120 s limits.
- Word matching for languages written without spaces.
- Row styling cache and faster chat updates in long matches.
- Settings saving, including saving when the panel closes quickly.
- JavaScript and Python settings agreeing on defaults, ranges and options.
- The customiser ignoring Mod Manager's switched-off copies, and saving
  everything else when artwork is switched on without an uploaded image.
- The release and audit scripts: missing or extra files, a missing token file,
  checksum line endings and the Mod ZIP contents (VPK, README, LICENSE,
  THIRD_PARTY, CHANGELOG, mod.json).

Final test counts: 112 Python and 27 Node tests pass. The release audit passes
with the owner's token file and a private-word check.

In-game check, 14 November 2026 (Deadlock 6861, one player, hideout and Sandbox
Mode):

- **Worked:** the CHAT MOD button shows in Settings and in the play menu footer.
  The new panel opens with all three tabs, and switching presets updates the
  preview. A typed line shows styled and fades after the 10 s timer. The
  character name shows ("PAIGE"), and switching to Both shows "PAIGE (NO_Zero)"
  straight away.
- **Fixed during the test:** the font picker label sat out of line, and sender
  names showed as "{s:sb_text}". Both are fixed in the released build, which
  is byte-identical to the one checked after the fixes.
- **Not checked in game:**
  - Other players' messages and "I'm with you" replies (no second player).
  - Objective and callout pings (the ping used went to the top bar, not chat).
  - Saving through the Windows customiser.
  - Hidden mode.

## 0.2.3

Fixes other players' messages disappearing at once instead of following the
Visible for timer. The game's chat creates each row with Expired already set,
and the old scanner only started timing on rows it saw unexpired. The fix starts
timing for newly seen or newly filled rows after the first history scan, and
leaves existing expired history alone.

The mock tests cover a remote-style expired row against a ten-second timer,
reused row content, old history, filters, mode changes and the ping lifecycle.
**Not tested with a real second player.** Don't call this fix confirmed.

On 1 November 2026, all 32 Python and 13 Node tests passed, and the new
regression test failed against the 0.2.2 script. On Deadlock 6839 / Steam
26349660 the replaced layouts matched the baseline. A one-human private session
(League preset, ten-second timer) showed a local message for about 4.7 seconds,
hid it by 16.8 seconds and brought it back when chat input reopened.

## 0.2.2

On 30 October 2026, two private one-human sessions on Deadlock 6833 / Steam
26335443 checked:

- The options panel stayed closed at launch and the Settings button opened it.
- Changing the timer from 10 to 11 seconds and back saved through the Windows customiser.
- A local message with the League preset and a character name, and a native
  Defend the Patron ping in gold.
- Timed history faded after closing input. Always visible kept history.
- Old pings cleared on returning to the hideout and in the next game.
- Afterwards the original preferences were back, with one installed copy.

Automated tests (32 Python, 11 Node) covered token handling, request checks,
strict PNG and VPK input, refusing duplicate or combined addon files, and
install and artwork locking. The release checks refused a stale executable and
scanned for private paths. The three ZIPs passed CRC, content and checksum
checks, and the public VPK has an empty token. The rebuilt executable
was inspected but not launched.

## 0.2

On 28 October 2026, private one-human tests on Deadlock 6821 / Steam 26224525
with Deadlock Mod Manager 2.2.0 covered the closed launch panel, live changes,
a three-second fade, Always visible, character, player and combined names,
native and hidden modes, character-wheel and objective pings, clearing old
pings between matches, and artwork upload.

## Not tested

- A real acknowledgement between two players, and other players' messages
  following the timer.
- Muting between several players, full-length matches, every language and
  resolution, controller input and future Valve updates.
- A fresh launch of the rebuilt Windows customiser.

Text categories use the wording shown on screen plus editable word lists. The
mod doesn't read hidden game state. Sources and runtime limits are in
`RESEARCH.md`; image sources are in `gallery/ASSETS.md`.
