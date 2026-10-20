# ZZZ Drive Disc Buff Overlay

A Windows overlay and combat-log tracker for **Zenless Zone Zero** Drive Disc 4-piece effects. It tails the game's combat logs, shows live buff timers next to the disc icons, follows the game window, and prints an end-of-battle DPS/uptime summary.

## Features

- Live per-character, per-set buff cards with stack counts and timers.
- Character-colored names, crisp outlined timer text, and a minimal transparent overlay.
- Drag/resize overlay with **F8**; click-through while locked.
- Follows the game window in windowed mode and remembers a game-relative position.
- Reads buff timing at the game's actual `timescale` rate, so timers slow/freeze during pauses, cutscenes, and Chain Attack slow-motion.
- Handles delayed Chain Attack slow onset by following the logged timescale rather than hard-coding per-attack lead times.
- Quick Assist detection from `events.tsv` for Astral Voice.
- Multi-window sets get one card per timed effect with short labels:
  - Woodpecker Electro: Basic / EX / Dodge
  - White Water Ballad: ATK / Veil
  - Shining Aria: Basic / Stun
- Hormone Punk displays a greyed 10s cooldown shadow after its 10s buff expires.
- Optional **OBS mode** so the overlay can be selected by OBS Window Capture.
- Portable path discovery: no hard-coded drive or user folder. It checks the running game folder, the script folder, the current folder, and common user folders.
- Optional end-of-battle damage, DPS, and buff-uptime summary.

## Requirements

- Windows 10/11
- Python 3.10+ (Tkinter included with standard Python installers)
- Pillow for PNG/WebP disc icons:

```powershell
python -m pip install pillow
```

## Usage

Auto-detect the `Combat Logs` folder:

```powershell
python D:\path\to\overl.py
```

Or point it at a logs root / single battle folder:

```powershell
python overl.py "C:\path\to\Combat Logs"
python overl.py "C:\path\to\Combat Logs\.diagnostics\2026-10-20 20.28.46\battle 1"
```

Useful options:

```text
--last                 Analyze the most recent completed fight and exit
--no-overlay           Disable the graphical overlay
--icons-dir DIR        Folder with Suit<Name>.png/.webp icons
--test-overlay         Preview the overlay and exit
--overlay-pos ...      Default corner when no overlay_config.json exists
--all-mods             Also show passive/listener modifiers
```

Environment variables `ZZZ_COMBAT_LOGS` or `ZZZ_LOG_DIR` can override log discovery.

### Overlay controls

- **F8** — unlock/lock the overlay for dragging/resizing.
- Drag the disc to move; drag the bottom-right grip or right-drag to resize.
- Double-click a card to toggle row/column layout.
- Position and size are saved in `overlay_config.json` next to the script.

## OBS recording

Use **OBS Window Capture**, not Game Capture (Game Capture only captures the game's own swapchain).

```powershell
# Transparent capture-friendly window
python overl.py --obs

# Opaque panel; most reliable for Window Capture
python overl.py --obs --obs-bg "#101014"
```

In OBS, add a **Window Capture** source and select `ZZZ Drive Disc Overlay (OBS)`. If the transparent window appears black or empty in a given capture method, use `--obs-bg` to make an opaque panel, or use OBS Display Capture.

## Data and behavior notes

Set metadata (durations, stack limits, refresh/decay behavior, and multi-window effects) was checked against the local `zzz-lb` `public/opt/data/gear-effects.json` data and the site's Drive Disc data. Some effects are inferred from combat-log modifier rows; the tracker is not a game-memory reader.

The tracker is a fan-made tool and is not affiliated with HoYoverse. Game names, icons, and assets belong to their respective owners.

## Icons

The script looks for icons named like `SuitAstralVoice.png` in:

1. `--icons-dir`
2. `icons/` next to the script
3. the script folder itself
