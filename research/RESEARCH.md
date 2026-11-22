# Research notes

Deadlock Chat Mod (internally "Switchboard") was researched on 28 October 2026
against Deadlock build 6821 / Steam 26224525. On 13 November 2026 the three
layouts it replaces were rechecked on 6861 / Steam 26546669 and are unchanged.
This file is in the Source ZIP only.

## Deadlock's chat

Deadlock is Valve's team game in early development, and its map, heroes and
interface still change. That is why the mod records exactly which game files it
replaces.

- Native chat is a `CitadelChat` C++ panel with Panorama XML and CSS for the look.
- `chat.xml` defines text, ping and sender snippets. Rows keep the game's own
  sender, channel, input, mute and expiry behaviour.
- Native chat sits near the bottom centre as grouped bubbles. The mod's layouts
  use the same rows in a compact left, centre or right panel.

Sources: the [Steam page](https://store.steampowered.com/app/1422450/Deadlock/),
the [City Never Sleeps page](https://www.playdeadlock.com/cityneversleeps) and
[Valve's Steam news](https://steamcommunity.com/app/1422450/allnews).

## Deadlock Mod Manager

Tested with 2.2.0 ([source](https://github.com/deadlock-mod-manager/deadlock-mod-manager),
commit `3d1f24ea4af87dfc906d07ee0b607df89b1cd10e`).

1. A local mod is added from a VPK, or an archive holding VPKs, through Mods
   Library, Add mods, Add Local Mod.
2. Enabled mods are installed as `pakNN_dir.vpk` in the addons folder. Switched-off
   copies stay in the same folder under other names, and state is kept in
   `addons/.dmm.json`.
3. A modded launch uses the addon search paths in `game/citadel/gameinfo.gi`.
   A game update can reset that file, so the manager writes it again.
4. Two mods that replace the same file conflict. This mod replaces the chat
   layout, the settings popup and the dashboard footer bar.

More in the manager's docs on [settings](https://docs.deadlockmods.app/using-mod-manager/settings)
and [customisation](https://docs.deadlockmods.app/using-mod-manager/customization).

## The chat presets

The presets are looks inspired by other games' chats, with plain fallback fonts.
They don't copy channels, commands, artwork or fonts.

| Preset | What it takes from the game | In the mod |
| --- | --- | --- |
| Overwatch 2 style | Open text rows, cyan team colour, translucent dark backing, separate input strip | Arial, cyan names, light background, square edges |
| Marvel Rivals style | Square dark panel, compact labels, strong team colours | Heavier Arial, darker panel, yellow accents, more line spacing |
| League of Legends style | Dense log, blue player names, gold objective text | Tahoma, small type, tight lines, gold pings |

References: Blizzard's [text chat changes](https://overwatch.blizzard.com/en-us/news/23985150/)
and [channel defaults](https://overwatch.blizzard.com/en-us/news/24009615/),
NetEase's [social settings update](https://www.marvelrivals.com/gameupdate/20250108/41548_1205270.html),
and Riot's [chat commands](https://support.riotgames.com/en-us/league-of-legends/gameplay/chat-commands/),
[party chat](https://www.leagueoflegends.com/en-us/news/game-updates/patch-13-4-notes/)
and [width and font options](https://www.leagueoflegends.com/en-au/news/game-updates/patch-10-25-notes/).
Screenshots of the three games' chats were used for visual study only, not for
keybinds or settings.

## How a UI mod is made

Deadlock uses Source 2 resources. A UI mod takes the original resources, changes
the layout, style or script, compiles them and packs a VPK with the same
internal paths.

| Source | Compiled |
| --- | --- |
| Panorama XML | `.vxml_c` |
| Panorama CSS | `.vcss_c` |
| Panorama script | `.vts_c` |
| PNG artwork | `.vtex_c` holding a bounded PNG |

Source 2 Viewer 20.1 is used to look at the game's resources. The mod's own
small packer writes the legacy text Panorama resources and a single-file VPK,
which the game loads. See [ValveResourceFormat](https://github.com/ValveResourceFormat/ValveResourceFormat)
and [Vergir's HUD project](https://github.com/Vergir/deadlock-4x3-fix-hud-resize).

## What the game's script allows

A probe in the game found no `GameUI`, `GameInterfaceAPI`, `Convars`, `UIState`
or `UiToolkitAPI`. `$.AsyncWebRequest` exists by name but does nothing. There is
no file access or settings storage.

- **Between panels:** settings pass through the `ClientUI_FireOutput` string
  event with a Switchboard prefix. New event names can't be assumed to work. The
  [UMM authors](https://xaohs.github.io/universal-mod-manager/authors/integration/)
  describe this channel. UMM isn't needed.
- **The Windows customiser** gives settings that last between sessions:
  - It listens on `127.0.0.1:18742` only and has no account or outside service.
  - In-game changes reach it as an image request with the settings in the URL.
    Chat text is never sent.
  - It stores settings in `%LOCALAPPDATA%\Switchboard` and rebuilds the VPK after
    the game closes.
  - It converts uploaded artwork to a bounded PNG. Artwork needs a restart; other
    changes apply live.
- **Without it,** the baked-in settings and in-game controls work for the
  session, and theme codes carry settings over.

## Names, responses and matches

- The top-bar player layout has `PlayerName` and `HeroName` labels. The mod pairs
  them to show character, player or both names. If a name is missing or unclear
  it uses the player label.
- The chat layout has a `HasResponse` state and `ResponseHeroes`, so portrait-only
  acknowledgements can be summarised next to the ping text. At most 40 rows are
  kept, for the current session only.
- The HUD has `InHideout` and pregame classes, and the top bar has `GameTime`.
  The mod uses these to mark old pings as stale when you return to the hideout,
  enter a new pregame or the match clock resets. Street Brawl countdowns are
  left out of the clock check.
- Objective filtering uses the words in the ping text, which you can edit for
  your language. Pings it doesn't recognise stay in the general ping category.

## What it doesn't do

It changes presentation and filters only. There is no DLL injection, no process
memory access, no entity scanning, no hidden enemy information, no network
inspection, no automatic messages and no match API calls. Channel limits and
mutes stay with Deadlock.

It isn't approved by Valve and isn't an account-safety guarantee; the game's
approach to community UI mods can change. The release records the layout CRCs
and the customiser refuses to install when they no longer match. What has and hasn't
been tested is in `VALIDATION.md`.
