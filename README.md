# Deadlock Chat Mod

By **Genkei**. Version 0.2.4.

[Download on GameBanana](https://gamebanana.com/mods/733556)

AI-assisted code: OpenAI Codex / ChatGPT and Anthropic Claude helped write,
debug and document the code. The screenshots are real Deadlock captures with a
title and an arrow added. No AI-generated images. Credits are in
[THIRD_PARTY.md](THIRD_PARTY.md).

Some file names and settings still say "Switchboard", the mod's old name.

## What it does

Restyles Deadlock's chat from a panel inside the game.

- Presets: Default, Overwatch 2 style, Marvel Rivals style, League of Legends
  style and Deadlock.
- Chat display: Styled, Deadlock or Hidden.
- Font, size, colours, width and spacing.
- A Visible for timer of up to 120 seconds.
- Filters for player messages, pings, callouts, objectives and system lines.
- Character or player names, and theme codes you can export and import.

It only changes how chat looks on your screen.

## Install

Close Deadlock first. Either install from GameBanana through Deadlock Mod
Manager's browser, or open Mods Library, choose Add mods, then Add Local Mod and
pick the ZIP you downloaded. Enable one copy only, then launch modded.

In game, open Settings and press **CHAT MOD** along the bottom.

## Settings

Changes apply straight away. Without the Windows customiser they last until the
game closes, so export a theme code if you want to keep them. Importing a code
only changes the look and filter settings.

## Windows customiser

An optional app (`Switchboard.exe`) that saves your settings between sessions
and adds custom background artwork. Message **genkei_ on Discord** and I'll
send it.

With the game closed, open it and use its install option once, then leave it
running while you play. It listens on 127.0.0.1:18742, keeps its files in
`%LOCALAPPDATA%\Switchboard` and never sends chat text anywhere.

## Removing it

Close the game, then disable or remove the mod in Mod Manager. If you installed
it by hand, delete the one Switchboard VPK from `game/citadel/addons`.

## Compatibility

The mod replaces three Deadlock layouts, so another UI mod that replaces the
same files will clash:

```
panorama/layout/chat.vxml_c
panorama/layout/popups/popup_settings.vxml_c
panorama/layout/citadel_dashboard_footer_bar.vxml_c
```

On 13 November 2026 these were checked on Deadlock 6861 / Steam 26546669 and
are unchanged from the version the mod was built against (6821 / Steam
26224525). If Valve changes them, the mod needs rebuilding.

Not tested yet: whether other players' messages follow the Visible for timer
(changed in 0.2.3). I haven't had a second player to try it with. Test notes
are in [research/VALIDATION.md](research/VALIDATION.md).

## Contributors

- **Genkei**: project owner, direction, player feedback, testing and releases.
- **OpenAI Codex / ChatGPT**: original implementation, research, debugging,
  automated tests, build tools and documentation.
- **Anthropic Claude**: substantial 0.2.4 changes, including the redesigned
  settings panel, runtime and Windows customiser fixes, tests, build checks,
  documentation and release work.

Codex and Claude are credited as AI development tools. Full third-party credits
and licence details are in [THIRD_PARTY.md](THIRD_PARTY.md).

## Building from source

Needs Python 3.11+ and Node 18+.

```powershell
python tools/build.py
node --test tests/runtime.test.js
python -m unittest discover -s tests -p "test_*.py"
```

The build writes `build/switchboard_dir.vpk`. Release steps are in
[PUBLISHING.md](PUBLISHING.md).

The code and original text are MIT licensed. Valve's layouts, fonts and game
captures stay with their owners.
