"""
Live Drive Disc Buff Tracker + Minimalist Disc Overlay + End-of-Battle DPS & Uptime.
- Portable setup: Combat Logs and icons are auto-detected from the game folder / script
  folder / common user folders (no hard-coded drive or user name).
- Zero-jolt F8 unlock/lock (hint banner floats in a separate window so discs never shift).
- Per-stack expiration timers for set effects with independent stacks. Effects such as
  Astral Voice that reset their duration on repeated triggers refresh every stack to the
  full duration (15s for Astral Voice).
- The overlay is anchored to the game's client area, so it follows the game window when
  it is moved in windowed mode.
- Multi-window sets (Woodpecker Electro, White Water Ballad, Shining Aria) get one card
  per timed window with a short label (Basic / EX / Dodge / Veil / ATK / Stun).
- Hormone Punk shows a greyed 10s downtime card after its 10s buff expires.
- `--obs` makes the window a normal app window for OBS Window Capture; `--obs-bg COLOR`
  switches it to an opaque capture panel.
- Astral Voice cards are also driven by Quick Assist switch-ins from events.tsv, so a
  QA entry always creates/refreshes the entering agent's card.
- Overlay timers follow the game timescale: they freeze during pauses/cutscenes and
  slow to the game's time-dilation rate during Chain Attack windows.
- Transparent timer & character name below the disc (no background box) with 1px crisp outline.
- Character names colored by their Attribute.
"""
import argparse
import ctypes
import datetime
import json
import math
import os
import queue
import re
import struct
import threading
import time
import tkinter as tk

try:
    from PIL import Image, ImageEnhance, ImageOps, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ICONS_DIR = os.path.join(SCRIPT_DIR, "icons")
OVERLAY_CONFIG_PATH = os.path.join(SCRIPT_DIR, "overlay_config.json")
STANDARD_FIGHT_DURATION_S = 180.0  # 3 minutes standard stage timer
LOGS_ROOT_ENV_VARS = ("ZZZ_COMBAT_LOGS", "ZZZ_LOG_DIR")
COMBAT_LOGS_DIR_NAMES = ("Combat Logs", "CombatLogs", "combat_logs")

# Exact Attribute -> Hex Color Table
ATTRIBUTE_COLORS = {
    "Physical": "#ffc100",
    "Fire": "#da3e3e",
    "Ice": "#a2cadf",
    "Electric": "#526ee9",
    "Ether": "#d852e6",
    "Frostbite": "#82b6d1",
    "Auric Ink": "#ecb43c",
    "Honed Edge": "#797cff",
    "Wind": "#88a7fe",
    "Lumiflux": "#fdb2e4",
    "Team": "#ffffff",
}

# Character Display Name -> Attribute Name
CHARACTER_ATTRIBUTE_MAP = {
    # Physical
    "Alice": "Physical", "Billy": "Physical", "Caesar": "Physical", "Corin": "Physical",
    "Dialyn": "Physical", "Jane": "Physical", "Nangong Yu": "Physical", "Nekomata": "Physical",
    "Pan Yinhu": "Physical", "Piper": "Physical", "Pulchra": "Physical",
    "Starlight - Billy": "Physical", "Sunna": "Physical", "Yuzuha": "Physical",
    # Fire
    "Banyue": "Fire", "Ben": "Fire", "Burnice": "Fire", "Evelyn": "Fire",
    "Ju Fufu": "Fire", "Koleda": "Fire", "Lighter": "Fire", "Lucy": "Fire",
    "Manato": "Fire", "Orphie & Magus": "Fire", "Phoenix": "Fire", "Pyrois": "Fire",
    "Soldier 11": "Fire",
    # Ice
    "Claret": "Ice", "Ellen": "Ice", "Hugo": "Ice", "Lycaon": "Ice",
    "Soukaku": "Ice", "Yidhari": "Ice", "Zhao": "Ice",
    # Frostbite
    "Miyabi": "Frostbite",
    # Electric
    "Anby": "Electric", "Anton": "Electric", "Cissia": "Electric", "Grace": "Electric",
    "Harumasa": "Electric", "Qingyi": "Electric", "Rina": "Electric", "Seed": "Electric",
    "Seth": "Electric", "Soldier 0 - Anby": "Electric", "Trigger": "Electric", "Yanagi": "Electric",
    # Ether
    "Aria": "Ether", "Astra Yao": "Ether", "Lucia": "Ether", "Nicole": "Ether",
    "Norma": "Ether", "Vivian": "Ether", "Zhu Yuan": "Ether",
    # Auric Ink
    "Yixuan": "Auric Ink",
    # Honed Edge
    "Ye Shunguang": "Honed Edge",
    # Wind
    "Roxy": "Wind", "Severian": "Wind", "Sigrid": "Wind",
    # Lumiflux
    "Promeia": "Lumiflux", "Remielle": "Lumiflux", "Velina": "Lumiflux",
}

# Internal codename -> In-game display name
CODENAME_MAP = {    "alice": "Alice", "anbi": "Anby", "anton": "Anton", "aokaku": "Soukaku",
    "aria": "Aria", "astra": "Astra Yao", "azural": "Dialyn", "banyue": "Banyue",
    "belle": "Belle", "ben": "Ben", "billy": "Billy", "brujas": "Orphie & Magus",
    "burnice": "Burnice", "caesar": "Caesar", "cissia": "Cissia", "clara": "Piper",
    "claret": "Claret", "corin": "Corin", "ellen": "Ellen", "evelyn": "Evelyn",
    "harumasa": "Harumasa", "hugovlad": "Hugo", "janedoe": "Jane", "jufufu": "Ju Fufu",
    "koleda": "Koleda", "lighter": "Lighter", "lisa": "Grace", "longinus": "Soldier 11",
    "lucia": "Lucia", "lucy": "Lucy", "lycaon": "Lycaon", "nangongyu": "Nangong Yu",
    "nicole": "Nicole", "norano": "Manato", "norma": "Norma", "nostradamus": "Nicole",
    "nos": "Nicole", "ookumamari": "Koleda", "panyinhu": "Pan Yinhu", "pheony": "Phoenix",
    "promeia": "Promeia", "pryce": "Roxy", "pulchra": "Pulchra", "pyrois": "Pyrois",
    "qingyi": "Qingyi", "remielle": "Remielle", "remielleorigin": "Remielle",
    "rina": "Rina", "seed": "Seed", "seth": "Seth", "severian": "Severian",
    "sigrid": "Sigrid", "silveranby": "Soldier 0 - Anby", "spbilly": "Starlight - Billy",
    "summer": "Sunna", "trigger": "Trigger", "tsubaki": "Nekomata", "unagi": "Miyabi",
    "velina": "Velina", "vivian": "Vivian", "wise": "Wise", "xiaozhao": "Zhao",
    "yanagi": "Yanagi", "yidhari": "Yidhari", "yixuan": "Yixuan", "yuzuha": "Yuzuha",
    "zhenzhen": "Ye Shunguang", "zhuyuan": "Zhu Yuan",
    "bangboo_plugboo": "Plugboo", "bangboo_brawlerboo": "Brawlerboo",
    "bangboo_luckyboo": "Luckyboo", "bangboo_resonaboo": "Resonaboo",
    "bangboo_sharkboo": "Sharkboo", "bangboo_bangboo": "Eous",
}

SKILL_PREFIX_MAP = {
    "1011": "Anby", "1021": "Nekomata", "1031": "Nicole", "1041": "Soldier 11",
    "1051": "Yidhari", "1061": "Corin", "1071": "Caesar", "1081": "Billy",
    "1091": "Miyabi", "1101": "Koleda", "1111": "Anton", "1121": "Ben",
    "1131": "Soukaku", "1141": "Lycaon", "1151": "Lucy", "1161": "Lighter",
    "1171": "Burnice", "1181": "Grace", "1191": "Ellen", "1201": "Harumasa",
    "1211": "Rina", "1221": "Yanagi", "1241": "Zhu Yuan", "1251": "Qingyi",
    "1261": "Jane", "1271": "Seth", "1281": "Piper", "1291": "Hugo",
    "1301": "Orphie & Magus", "1311": "Astra Yao", "1321": "Evelyn", "1331": "Vivian",
    "1341": "Zhao", "1351": "Pulchra", "1361": "Trigger", "1371": "Yixuan",
    "1381": "Soldier 0 - Anby", "1391": "Ju Fufu", "1401": "Alice", "1411": "Yuzuha",
    "1421": "Pan Yinhu", "1431": "Ye Shunguang", "1441": "Manato", "1451": "Lucia",
    "1461": "Seed", "1471": "Banyue", "1481": "Dialyn", "1491": "Sunna",
    "1501": "Aria", "1511": "Nangong Yu", "1521": "Cissia", "1531": "Starlight - Billy",
    "1541": "Promeia", "1551": "Pyrois", "1561": "Velina", "1571": "Norma",
    "1581": "Remielle", "1591": "Sigrid", "1611": "Claret", "1621": "Roxy",
    "1631": "Severian", "1641": "Phoenix",
}

# Complete 30 Drive Disc Set Map.
# Duration/stack/refresh/decay flags mirror zzz-lb public/opt/data/gear-effects.json.
DISC_SET_MAP = {
    "50431000": {"name": "Woodpecker Electro (4pc)", "icon": "SuitWoodpeckerElectro", "dur": "6s", "dur_s": 6.0, "max_stacks": 3, "units": [0.09], "color": "#FF6B6B"},
    "50431100": {"name": "Puffer Electro (4pc)", "icon": "SuitPufferElectro", "dur": "12s", "dur_s": 12.0, "refresh_skills": ("ultimate",), "color": "#4DABF7"},
    "50431200": {"name": "Shockstar Disco (4pc)", "icon": "SuitShockstarDisco", "dur": "Passive", "dur_s": 0.0, "color": "#FFD43B"},
    "50431300": {"name": "Freedom Blues (4pc)", "icon": "SuitFreedomBlues", "dur": "8s", "dur_s": 8.0, "refresh_skills": ("ex",), "color": "#74C0FC"},
    "50431400": {"name": "Hormone Punk (4pc)", "icon": "SuitHormonePunk", "dur": "10s", "dur_s": 10.0, "shadow_s": 10.0, "color": "#69DB7C"},
    "50431500": {"name": "Soul Rock (4pc)", "icon": "SuitSoulRock", "dur": "2.5s", "dur_s": 2.5, "color": "#FFA94D"},
    "50431600": {"name": "Swing Jazz (4pc)", "icon": "SuitSwingJazz", "dur": "12s", "dur_s": 12.0, "teamwide": True, "refresh_skills": ("ultimate", "chain"), "color": "#FCC419"},
    "50431800": {"name": "Chaos Jazz (4pc)", "icon": "SuitChaosJazz", "dur": "5s", "dur_s": 5.0, "color": "#FF8787"},
    "50431900": {"name": "Proto Punk (4pc)", "icon": "SuitProtoPunk", "dur": "10s", "dur_s": 10.0, "teamwide": True, "color": "#A9E34B"},
    "50431901": {"name": "Proto Punk (2pc)", "icon": "SuitProtoPunk", "dur": "Passive", "dur_s": 0.0, "color": "#A9E34B"},
    "50432200": {"name": "Inferno Metal (4pc)", "icon": "SuitInfernoMetal", "dur": "8s", "dur_s": 8.0, "color": "#FF5252", "elem": "Fire"},
    "50432300": {"name": "Chaotic Metal (4pc)", "icon": "SuitChaosMetal", "dur": "8s", "dur_s": 8.0, "max_stacks": 6, "units": [0.055], "refresh_all": True, "color": "#DA77F2", "elem": "Ether"},
    "50432400": {"name": "Thunder Metal (4pc)", "icon": "SuitThunderMetal", "dur": "Active", "dur_s": 10.0, "no_auto_expire": True, "color": "#3BC9DB", "elem": "Electric"},
    "50432500": {"name": "Polar Metal (4pc)", "icon": "SuitPolarMetal", "dur": "12s", "dur_s": 12.0, "color": "#91A7FF", "elem": "Ice"},
    "50432600": {"name": "Fanged Metal (4pc)", "icon": "SuitFangedMetal", "dur": "12s", "dur_s": 12.0, "color": "#FFD8A8", "elem": "Physical"},
    "50432700": {"name": "Branch & Blade Song (4pc)", "icon": "SuitBranch&BladeSong", "dur": "15s", "dur_s": 15.0, "color": "#66D9E8"},
    "50432800": {"name": "Astral Voice (4pc)", "icon": "SuitAstralVoice", "dur": "15s", "dur_s": 15.0, "max_stacks": 3, "units": [0.08, 0.10], "teamwide": False, "refresh_all": True, "color": "#E599F7"},
    "50432900": {"name": "Shadow Harmony (4pc)", "icon": "SuitShadow", "dur": "15s", "dur_s": 15.0, "max_stacks": 3, "units": [0.04, 0.05, 0.10], "refresh_all": True, "color": "#B197FC"},
    "50433000": {"name": "Phaethon's Melody (4pc)", "icon": "SuitPhaethonsMelody", "dur": "8s", "dur_s": 8.0, "refresh_skills": ("ex",), "refresh_on_any_ex": True, "color": "#CC5DE8"},
    "50433100": {"name": "Yunkui Tales (4pc)", "icon": "SuitYunkuiTales", "dur": "15s", "dur_s": 15.0, "max_stacks": 3, "units": [0.04], "refresh_all": True, "refresh_skills": ("ex", "ultimate", "chain"), "color": "#F783AC"},
    "50433200": {"name": "King of the Summit (4pc)", "icon": "SuitKingoftheSummit", "dur": "15s", "dur_s": 15.0, "teamwide": True, "refresh_skills": ("ex", "chain"), "color": "#FAB005"},
    "50433300": {"name": "Dawn's Bloom (4pc)", "icon": "SuitDawn'sBloom", "dur": "25s", "dur_s": 25.0, "refresh_skills": ("ex", "ultimate"), "color": "#63E6BE"},
    "50433400": {"name": "Moonlight Lullaby (4pc)", "icon": "SuitMoonlightLullaby", "dur": "25s", "dur_s": 25.0, "teamwide": True, "refresh_skills": ("ex", "ultimate"), "color": "#748FFC"},
    "50433500": {"name": "White Water Ballad (4pc)", "icon": "SuitWhiteWaterBallad", "dur": "15s/30s", "dur_s": 15.0, "color": "#A5D8FF", "elem": "Physical"},
    "50433600": {"name": "Shining Aria (4pc)", "icon": "SuitShiningAria", "dur": "8s/18s", "dur_s": 18.0, "color": "#EEBEFA", "elem": "Ether"},
    "50433700": {"name": "Bunny in Wonderland (4pc)", "icon": "SuitBunnyinWonderland", "dur": "25s", "dur_s": 25.0, "max_stacks": 3, "units": [0.06], "teamwide": True, "refresh_all": True, "decay_one": True, "refresh_skills": ("ex",), "refresh_on_assist": True, "color": "#FFADAD"},
    "50433800": {"name": "Notes From the Chained (4pc)", "icon": "SuitNotesFromtheChained", "dur": "30s", "dur_s": 30.0, "color": "#99E9F2", "elem": "Ice"},
    "50433900": {"name": "Wuthering Salon (4pc)", "icon": "SuitWutheringSalon", "dur": "40s", "dur_s": 40.0, "max_stacks": 2, "units": [25.0], "refresh_all": True, "refresh_skills": ("ex",), "color": "#8CE99A", "elem": "Wind"},
    "50434000": {"name": "The Sky Ablaze (4pc)", "icon": "SuitTheSkyAblaze", "dur": "30s", "dur_s": 30.0, "refresh_skills": ("ex", "ultimate"), "color": "#FF922B", "elem": "Ether"},
    "50434100": {"name": "Feathered Fate (4pc)", "icon": "SuitFeatheredFate", "dur": "15s", "dur_s": 15.0, "color": "#FFE066", "elem": "Lumiflux"},
    "50434200": {"name": "Thorned Rose (4pc)", "icon": "SuitThornedRose", "dur": "Passive", "dur_s": 0.0, "color": "#F06595"},
    # 2-Piece Set Effects
    "50232200": {"name": "Inferno Metal (2pc)", "icon": "SuitInfernoMetal", "dur": "Passive", "dur_s": 0.0, "elem": "Fire"},
    "50232300": {"name": "Chaotic Metal (2pc)", "icon": "SuitChaosMetal", "dur": "Passive", "dur_s": 0.0, "elem": "Ether"},
    "50232400": {"name": "Thunder Metal (2pc)", "icon": "SuitThunderMetal", "dur": "Passive", "dur_s": 0.0, "elem": "Electric"},
    "50232500": {"name": "Polar Metal (2pc)", "icon": "SuitPolarMetal", "dur": "Passive", "dur_s": 0.0, "elem": "Ice"},
    "50232600": {"name": "Fanged Metal (2pc)", "icon": "SuitFangedMetal", "dur": "Passive", "dur_s": 0.0, "elem": "Physical"},
    "50232900": {"name": "Woodpecker/Shadow (2pc)", "icon": "SuitWoodpeckerElectro", "dur": "Passive", "dur_s": 0.0},
}

# Modifier names that do not carry a usable Suit_Ability_<id> string.
MODIFIER_SET_ALIASES = {
    "BaseAttackRatioModifier_01": "50431000",  # Woodpecker: Basic window
    "BaseAttackRatioModifier_02": "50431000",  # Woodpecker: EX window
    "BaseAttackRatioModifier_03": "50431000",  # Woodpecker: Dodge window
    "AddedDamageRatioModifier_Exsp_02": "50431800",  # Chaos Jazz continuation
    "UniqueBuffModifier_50433200": "50433200",        # King of the Summit
    "UniqueBuffModifier_Extra_50433200": "50433200",  # King of the Summit extra CD
}

# Sets whose 4pc has more than one independent timed window.  Each effect gets
# its own overlay card instead of collapsing them into one misleading timer.
DEFAULT_EFFECT_KEY = "main"
DISC_EFFECTS = {
    "50431000": [
        {"key": "basic", "label": "Basic", "dur": "6s", "dur_s": 6.0,
         "hints": ("BaseAttackRatioModifier_01", "basic attack", "attacksnormal")},
        {"key": "ex", "label": "EX", "dur": "6s", "dur_s": 6.0,
         "hints": ("BaseAttackRatioModifier_02", "ex special", "exspecial")},
        {"key": "dodge", "label": "Dodge", "dur": "6s", "dur_s": 6.0,
         "hints": ("BaseAttackRatioModifier_03", "dodge counter", "dodgecounter")},
    ],
    "50433500": [
        {"key": "atk", "label": "ATK", "dur": "30s", "dur_s": 30.0,
         "hints": ("bycaster", "prolong", "activate", "extend", "themespace start", "themespace_start")},
        {"key": "veil", "label": "Veil", "dur": "15s", "dur_s": 15.0,
         "hints": ("inveil", "in veil", "themespace")},
    ],
    "50433600": [
        {"key": "basic", "label": "Basic", "dur": "8s", "dur_s": 8.0,
         "hints": ("basic", "attacknormal", "normal")},
        {"key": "stun", "label": "Stun", "dur": "18s", "dur_s": 18.0,
         "hints": ("stun", "breakstun")},
    ],
}


def get_effect_config(suit_id: str, effect_key: str = DEFAULT_EFFECT_KEY):
    """Return merged set/effect metadata for one timed window."""
    info = DISC_SET_MAP.get(suit_id, {})
    effects = DISC_EFFECTS.get(suit_id) or info.get("effects") or []
    if not effects:
        cfg = dict(info)
        cfg.setdefault("key", DEFAULT_EFFECT_KEY)
        cfg.setdefault("label", "")
        cfg.setdefault("dur", info.get("dur", "Active"))
        cfg.setdefault("dur_s", info.get("dur_s", 15.0))
        cfg.setdefault("max_stacks", info.get("max_stacks", 1))
        cfg.setdefault("refresh_all", info.get("refresh_all", False))
        cfg.setdefault("decay_one", info.get("decay_one", False))
        cfg.setdefault("no_auto_expire", info.get("no_auto_expire", False))
        return cfg, info

    keys = {e.get("key", DEFAULT_EFFECT_KEY) for e in effects}
    if effect_key not in keys:
        effect_key = effects[0].get("key", DEFAULT_EFFECT_KEY)
    effect = next(e for e in effects if e.get("key", DEFAULT_EFFECT_KEY) == effect_key)

    cfg = dict(info)
    cfg.update(effect)
    cfg["key"] = effect_key
    cfg["label"] = effect.get("label", "")
    cfg["dur"] = effect.get("dur", info.get("dur", "Active"))
    cfg["dur_s"] = effect.get("dur_s", info.get("dur_s", 15.0))
    cfg["max_stacks"] = effect.get("max_stacks", 1)
    cfg["refresh_all"] = effect.get("refresh_all", False)
    cfg["decay_one"] = effect.get("decay_one", False)
    cfg["no_auto_expire"] = effect.get("no_auto_expire", False)
    return cfg, info


def resolve_effect_key(suit_id: str, mod_name: str = "", ability: str = "") -> str:
    """Pick the timed window from a modifier/ability string, when possible."""
    effects = DISC_EFFECTS.get(suit_id) or DISC_SET_MAP.get(suit_id, {}).get("effects") or []
    if not effects:
        return DEFAULT_EFFECT_KEY
    blob = f"{mod_name or ''} {ability or ''}".lower()
    for effect in effects:
        if any(h.lower() in blob for h in effect.get("hints", ())):
            return effect.get("key", DEFAULT_EFFECT_KEY)
    return effects[0].get("key", DEFAULT_EFFECT_KEY)

ELEMENT_CODE_MAP = {
    "200": "Physical",
    "201": "Fire",
    "202": "Ice",
    "203": "Electric",
    "204": "Wind",
    "205": "Ether",
}

DISK_ID_ANY_RE = re.compile(r"(?<!\d)(50[24]3\d{4})(?!\d)")
DISK_SUIT_RE = re.compile(r"Suit_(?:Ability_)?(\d+)", re.IGNORECASE)
DISK_RES_RE = re.compile(r"AbnormalResistDelta(?:Modifier)?_(\d+)(?:_Suit_Ability_(\d+))?", re.IGNORECASE)
SUIT_ABILITY_RE = re.compile(r"Suit_Ability_(5043\d{4})", re.IGNORECASE)
ASSIST_TRIGGER_MODIFIERS = {
    "HeavyParryModifer",
    "PerfectEvadeModifier_Invincible",
    "EvadeAid",
    "EvasiveAid",
    "ParryAid",
}
BATTLE_DIR_RE = re.compile(r"^battle\s+(\d+)(?:\s*\((\d+)\))?$", re.IGNORECASE)
DATE_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Windows helpers: locate the game window / its install folder, and keep the
# overlay anchored to the game's client area while the window is moved.
# ---------------------------------------------------------------------------
class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


_USER32 = None
_KERNEL32 = None
_ENUM_WINDOWS_PROC = None


def _win32():
    """Lazily load and type the Win32 calls used by the overlay."""
    global _USER32, _KERNEL32, _ENUM_WINDOWS_PROC
    if os.name != "nt":
        return None, None
    if _USER32 is not None:
        return _USER32, _KERNEL32
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        _ENUM_WINDOWS_PROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        user32.EnumWindows.argtypes = [_ENUM_WINDOWS_PROC, ctypes.c_void_p]
        user32.EnumWindows.restype = ctypes.c_bool
        user32.IsWindow.argtypes = [ctypes.c_void_p]
        user32.IsWindow.restype = ctypes.c_bool
        user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
        user32.IsWindowVisible.restype = ctypes.c_bool
        user32.IsIconic.argtypes = [ctypes.c_void_p]
        user32.IsIconic.restype = ctypes.c_bool
        user32.GetWindowTextLengthW.argtypes = [ctypes.c_void_p]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
        user32.GetClassNameW.restype = ctypes.c_int
        user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(_RECT)]
        user32.GetWindowRect.restype = ctypes.c_bool
        user32.GetClientRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(_RECT)]
        user32.GetClientRect.restype = ctypes.c_bool
        user32.ClientToScreen.argtypes = [ctypes.c_void_p, ctypes.POINTER(_POINT)]
        user32.ClientToScreen.restype = ctypes.c_bool
        user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        user32.GetWindowThreadProcessId.restype = ctypes.c_ulong

        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.QueryFullProcessImageNameW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_wchar_p,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        kernel32.QueryFullProcessImageNameW.restype = ctypes.c_bool
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_bool

        _USER32 = user32
        _KERNEL32 = kernel32
        return _USER32, _KERNEL32
    except Exception:
        return None, None


def _enum_top_level_windows():
    user32, _ = _win32()
    if user32 is None:
        return []
    handles = []

    @_ENUM_WINDOWS_PROC
    def _callback(hwnd, _lparam):
        handles.append(hwnd)
        return True

    try:
        user32.EnumWindows(_callback, 0)
    except Exception:
        return []
    return handles


def _get_window_title(user32, hwnd) -> str:
    try:
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value or ""
    except Exception:
        return ""


def _get_window_class(user32, hwnd) -> str:
    try:
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, len(buf))
        return buf.value or ""
    except Exception:
        return ""


def _get_window_process_path(user32, kernel32, hwnd) -> str:
    try:
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""
        handle = kernel32.OpenProcess(0x1000, False, pid.value)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(32768)
            size = ctypes.c_ulong(len(buf))
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return buf.value or ""
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        pass
    return ""


def find_game_window():
    """Return (hwnd, exe_path) for the ZZZ window, or None if it is not found."""
    user32, kernel32 = _win32()
    if user32 is None:
        return None

    strong = []
    weak = []
    for hwnd in _enum_top_level_windows():
        try:
            if not user32.IsWindowVisible(hwnd):
                continue
            rect = _RECT()
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                continue
            width = max(0, rect.right - rect.left)
            height = max(0, rect.bottom - rect.top)
            if width < 100 or height < 100:
                continue

            title = _get_window_title(user32, hwnd)
            window_class = _get_window_class(user32, hwnd)
            exe_path = _get_window_process_path(user32, kernel32, hwnd)
            exe_name = os.path.basename(exe_path).casefold()
            title_low = title.casefold()

            if "zenlesszonezero" in exe_name:
                strong.append((width * height, hwnd, exe_path))
            elif ("zenless" in title_low or "绝区零" in title) and (
                "unity" in window_class.casefold()
                or title_low in ("zenless zone zero", "zenlesszonezero")
                or "绝区零" in title
            ):
                weak.append((width * height, hwnd, exe_path))
        except Exception:
            continue

    matches = strong or weak
    if not matches:
        return None
    matches.sort(key=lambda item: item[0], reverse=True)
    return matches[0][1], matches[0][2]


def get_window_client_origin(hwnd):
    """Return the screen-space (x, y) of a window's client-area top-left."""
    user32, _ = _win32()
    if user32 is None or not hwnd:
        return None
    try:
        if not user32.IsWindow(hwnd) or user32.IsIconic(hwnd):
            return None
        client = _RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(client)):
            return None
        if client.right <= 0 or client.bottom <= 0:
            return None
        point = _POINT(0, 0)
        if not user32.ClientToScreen(hwnd, ctypes.byref(point)):
            return None
        return int(point.x), int(point.y)
    except Exception:
        return None


def _expand_path(path: str) -> str:
    return os.path.abspath(os.path.expanduser(os.path.expandvars(str(path))))


def _looks_like_combat_logs(path: str) -> bool:
    if not path or not os.path.isdir(path):
        return False
    if os.path.isdir(os.path.join(path, ".diagnostics")):
        return True
    try:
        for entry in os.scandir(path):
            if entry.is_dir() and DATE_DIR_RE.match(entry.name):
                return True
    except OSError:
        pass
    return False


def _logs_root_score(path: str) -> float:
    score = 0.0
    try:
        score = max(score, os.path.getmtime(path))
    except OSError:
        pass
    try:
        diag = os.path.join(path, ".diagnostics")
        if os.path.isdir(diag):
            score = max(score, os.path.getmtime(diag))
    except OSError:
        pass
    try:
        for entry in os.scandir(path):
            if entry.is_dir() and DATE_DIR_RE.match(entry.name):
                try:
                    score = max(score, entry.stat().st_mtime)
                except OSError:
                    pass
    except OSError:
        pass
    return score


def _candidate_logs_roots():
    """Build a de-duplicated list of likely Combat Logs roots."""
    candidates = []
    seen = set()

    def add(path):
        path = os.path.normpath(path)
        key = os.path.normcase(path)
        if key not in seen:
            seen.add(key)
            candidates.append(path)

    for var in LOGS_ROOT_ENV_VARS:
        value = os.environ.get(var)
        if value:
            add(_expand_path(value))

    game = find_game_window()
    if game and game[1]:
        game_dir = os.path.dirname(game[1])
        for name in COMBAT_LOGS_DIR_NAMES:
            add(os.path.join(game_dir, name))

    home = os.path.expanduser("~")
    direct_bases = [
        SCRIPT_DIR,
        os.path.dirname(SCRIPT_DIR),
        os.getcwd(),
        home,
        os.path.join(home, "Downloads"),
        os.path.join(home, "Documents"),
        os.path.join(home, "Desktop"),
        os.path.join(home, "OneDrive", "Desktop"),
    ]
    for base in direct_bases:
        for name in COMBAT_LOGS_DIR_NAMES:
            add(os.path.join(base, name))

    # One level below common install/download folders (e.g. ...\zzzbeta\Combat Logs).
    scan_bases = [
        os.path.join(home, "Downloads"),
        os.path.join(home, "Documents"),
        os.path.join(home, "Desktop"),
        os.path.dirname(SCRIPT_DIR),
        os.getcwd(),
    ]
    for base in scan_bases:
        try:
            with os.scandir(base) as entries:
                for index, entry in enumerate(entries):
                    if index >= 250:
                        break
                    try:
                        if not entry.is_dir():
                            continue
                    except OSError:
                        continue
                    for name in COMBAT_LOGS_DIR_NAMES:
                        add(os.path.join(entry.path, name))
        except OSError:
            continue

    return candidates


def discover_logs_root():
    """Auto-detect the folder that contains Combat Logs (no machine-specific path)."""
    for var in LOGS_ROOT_ENV_VARS:
        value = os.environ.get(var)
        if value:
            path = _expand_path(value)
            if _looks_like_combat_logs(path):
                return path

    best_path = None
    best_score = float("-inf")
    for candidate in _candidate_logs_roots():
        if not _looks_like_combat_logs(candidate):
            continue
        score = _logs_root_score(candidate)
        if score > best_score:
            best_path = candidate
            best_score = score
    return best_path


DEFAULT_LOGS_ROOT = discover_logs_root()


HELPER_MOD_RE = re.compile(
    r"(?:^__DEFAULT_MODIFIER$|Listener|Controller|_CD$|^ProtectModifier$|^StackCountTimerModifier$|^BuffModifier_Provider$|^PropModifier$)",
    re.IGNORECASE,
)


def extract_suit_id(mod_name: str, mod_ability: str = ""):
    if mod_name:
        alias = MODIFIER_SET_ALIASES.get(mod_name)
        if alias:
            return alias
    # The game uses Suit50433600_DamgeUpModifier for Bunny in Wonderland
    # (50433700), even though 50433600 is Shining Aria.  Some trigger rows
    # only expose this modifier name, so resolve it explicitly.
    if mod_name and "50433600" in mod_name and re.search(r"DamgeUpModifier", mod_name, re.IGNORECASE):
        return "50433700"
    for candidate in (mod_ability, mod_name):
        if not candidate:
            continue
        m_any = DISK_ID_ANY_RE.search(candidate)
        if m_any:
            return m_any.group(1)
        m_suit = DISK_SUIT_RE.search(candidate)
        if m_suit:
            return m_suit.group(1)
        m_res = DISK_RES_RE.search(candidate)
        if m_res:
            return m_res.group(2) or "50431300"
    return None


def classify_disc_buff(mod_name: str, mod_ability: str = "", include_passive: bool = False):
    suit_id = extract_suit_id(mod_name, mod_ability)
    if not suit_id:
        return None

    clean_mod = mod_name or f"Suit_Ability_{suit_id}"
    if not include_passive and HELPER_MOD_RE.search(clean_mod):
        return None

    info = DISC_SET_MAP.get(suit_id)
    if info:
        if not include_passive and info.get("dur") == "Passive":
            return None
        set_name = info["name"]
        dur_str = info["dur"]
    else:
        set_name = f"Disc Set [{suit_id}]"
        dur_str = "Active"

    return (suit_id, set_name, dur_str)


def extract_codename_from_str(text: str):
    if not text:
        return None
    low = text.lower()
    if low.startswith(("suit_", "weapon_", "player_", "monster_")):
        return None
    parts = low.split("_")
    prefix = parts[0]
    if prefix == "bangboo" and len(parts) > 1:
        prefix = f"{parts[0]}_{parts[1]}"
    elif prefix.startswith("nosunique"):
        prefix = "nos"
    return CODENAME_MAP.get(prefix)


def extract_element_from_str(text: str):
    """Detects an attribute keyword or element code from a modifier/ability string."""
    if not text:
        return None
    m_res = DISK_RES_RE.search(text)
    if m_res and m_res.group(1) in ELEMENT_CODE_MAP:
        return ELEMENT_CODE_MAP[m_res.group(1)]
    low = text.lower()
    if "frostbite" in low:
        return "Frostbite"
    if "auric" in low:
        return "Auric Ink"
    if "honed" in low:
        return "Honed Edge"
    if "lumiflux" in low or "lumen" in low:
        return "Lumiflux"
    if "_physics" in low or "element_physics" in low:
        return "Physical"
    if "_fire" in low or "element_fire" in low:
        return "Fire"
    if "_ice" in low or "element_ice" in low:
        return "Ice"
    if "_elec" in low or "element_elec" in low:
        return "Electric"
    if "_wind" in low or "element_wind" in low:
        return "Wind"
    if "_ether" in low or "element_ether" in low:
        return "Ether"
    return None


def get_character_color(char_name: str, detected_attr: str = None) -> str:
    """Returns the hex color for a character's name based on their Attribute."""
    if not char_name or char_name == "Team":
        return ATTRIBUTE_COLORS["Team"]
    # Preserve special sub-attributes for Miyabi / Yixuan / Ye Shunguang
    mapped_attr = CHARACTER_ATTRIBUTE_MAP.get(char_name)
    if mapped_attr in ("Frostbite", "Auric Ink", "Honed Edge"):
        return ATTRIBUTE_COLORS[mapped_attr]
    attr = detected_attr or mapped_attr
    return ATTRIBUTE_COLORS.get(attr, "#ffffff")


def merge_intervals(intervals):
    if not intervals:
        return 0.0
    sorted_iv = sorted(intervals, key=lambda x: x[0])
    merged = [list(sorted_iv[0])]
    for start, end in sorted_iv[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return sum(max(0.0, end - start) for start, end in merged)


def norm_filename_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def format_holder_label(holder_name: str, effect_label: str = "") -> str:
    if not effect_label:
        return (holder_name or "")[:12]
    return f"{(holder_name or '')[:10]} {effect_label}"[:16]


class DiscOverlayHUD:
    """
    Minimalist Drive Disc Overlay:
    - Zero-jolt F8 unlock/lock: hint bar lives in a separate floating Toplevel window above the discs.
    - Independent per-stack timers for most sets; effects with refresh_all reset every stack
      to the full duration on repeated triggers.
    - Anchored to the game client area so it follows the game window in windowed mode.
    - Transparent timer & attribute-colored character name below the disc (no rectangular box).
    """
    TRANSPARENT_KEY = "#010101"
    TEXT_OUTLINE = "#08080C"
    BADGE_BG = "#111318"
    VK_F8 = 0x77

    def __init__(self, icons_dir: str = DEFAULT_ICONS_DIR, position: str = "top-right",
                 obs_mode: bool = False, obs_bg: str = None):
        self.icons_dir = icons_dir
        self.default_pos = position
        self.obs_mode = bool(obs_mode or obs_bg)
        self.obs_bg = obs_bg
        if obs_bg:
            # Opaque OBS mode: no transparent-color key, solid panel background.
            self.TRANSPARENT_KEY = obs_bg
        self.cmd_queue = queue.Queue()
        self.cards = {}          # group_key -> card dict
        self.raw_pil_cache = {}  # suit_id -> PIL.Image
        self.icon_cache = {}     # (suit_id, px_size) -> PhotoImage
        self.file_index = {}     # normalized_stem -> full_filepath
        self.warned_webp = False

        self.cfg = {
            "x": None,
            "y": 60,
            "icon_size": 76,         # Disc diameter in pixels (36..220)
            "layout": "horizontal",  # "horizontal" or "vertical"
            "follow_game_window": True,
            "offset_x": None,        # position relative to the game client area
            "offset_y": None,
        }
        self._load_config()
        self._index_icon_files()

        self.edit_mode = False
        self.f8_was_down = False
        self.time_scale = 1.0
        self._timer_last = time.perf_counter()
        self._timer_offset = 0.0
        self._drag_mode = None
        self._drag_start = (0, 0, 0, 0)
        self._game_hwnd = None
        self._game_origin = None
        self._last_game_scan = 0.0

        self.root = None
        self.hint_win = None
        self.container = None

        self.thread = threading.Thread(target=self._run_gui, daemon=True)
        self.thread.start()

    def _load_config(self):
        if os.path.isfile(OVERLAY_CONFIG_PATH):
            try:
                with open(OVERLAY_CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    if "scale" in data and "icon_size" not in data:
                        data["icon_size"] = int(round(76 * float(data["scale"])))
                    self.cfg.update(data)
            except Exception:
                pass
        self.cfg["icon_size"] = max(36, min(220, int(self.cfg.get("icon_size", 76))))
        if self.cfg.get("layout") not in ("horizontal", "vertical"):
            self.cfg["layout"] = "horizontal"
        self.cfg["follow_game_window"] = bool(self.cfg.get("follow_game_window", True))
        for key in ("offset_x", "offset_y"):
            try:
                if self.cfg.get(key) is not None:
                    self.cfg[key] = int(self.cfg[key])
            except (TypeError, ValueError):
                self.cfg[key] = None

    def _save_config(self):
        try:
            if self.root is not None:
                self.cfg["x"] = self.root.winfo_x()
                self.cfg["y"] = self.root.winfo_y()
                origin = self._game_origin
                if self._game_hwnd:
                    origin = get_window_client_origin(self._game_hwnd) or origin
                if origin is not None:
                    self._game_origin = origin
                    self.cfg["offset_x"] = self.cfg["x"] - origin[0]
                    self.cfg["offset_y"] = self.cfg["y"] - origin[1]
            with open(OVERLAY_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, indent=2)
        except Exception:
            pass

    def _index_icon_files(self):
        self.file_index.clear()
        for folder in (self.icons_dir, SCRIPT_DIR):
            if not os.path.isdir(folder):
                continue
            try:
                for fname in os.listdir(folder):
                    stem, ext = os.path.splitext(fname)
                    if ext.lower() not in (".png", ".webp", ".jpg", ".jpeg", ".gif"):
                        continue
                    full_path = os.path.join(folder, fname)
                    norm = norm_filename_key(stem)
                    if norm not in self.file_index or ext.lower() == ".png":
                        self.file_index[norm] = full_path
                    self.file_index[stem.lower()] = full_path
            except OSError:
                pass

    def set_time_scale(self, scale: float):
        """Follow the game's timescale so buff timers slow/freeze with game time."""
        self.cmd_queue.put(("time_scale", float(scale)))

    def _game_now(self, real_now: float = None) -> float:
        return (real_now if real_now is not None else time.perf_counter()) - self._timer_offset

    def _advance_clock(self, real_now: float):
        # Chain Attack windows stay near scale 1 for a per-attack lead before
        # dropping to ~1.5%; following the logged scale avoids hard-coding the
        # 0.05-1.6s lead values.
        dt = max(0.0, real_now - self._timer_last)
        self._timer_last = real_now
        scale = max(0.0, min(1.0, self.time_scale))
        self._timer_offset += dt * (1.0 - scale)

    def _apply_time_scale(self, scale: float, real_now: float):
        self._advance_clock(real_now)
        self.time_scale = max(0.0, min(1.0, float(scale)))

    def notify_buff(self, group_key, suit_id: str, set_name: str, holder_name: str, holder_color: str, stacks: int, duration_s: float, add_stack: bool = True, effect_key: str = DEFAULT_EFFECT_KEY, effect_label: str = ""):
        self.cmd_queue.put(("upsert", group_key, suit_id, set_name, holder_name, holder_color, stacks, duration_s, add_stack, effect_key, effect_label))

    def pop_stack(self, group_key, expected_stacks: int = None):
        self.cmd_queue.put(("pop_stack", group_key, expected_stacks))

    def update_holder_info(self, group_key, holder_name: str, holder_color: str):
        self.cmd_queue.put(("rename", group_key, holder_name, holder_color))

    def remove_buff(self, group_key):
        self.cmd_queue.put(("remove", group_key))

    def clear_all(self):
        self.cmd_queue.put(("clear",))

    def _set_window_click_through(self, win, enabled: bool):
        try:
            user32 = ctypes.windll.user32
            user32.GetParent.argtypes = [ctypes.c_void_p]
            user32.GetParent.restype = ctypes.c_void_p
            user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
            user32.GetWindowLongW.restype = ctypes.c_long
            user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
            user32.SetWindowLongW.restype = ctypes.c_long
            user32.SetWindowDisplayAffinity.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            user32.SetWindowDisplayAffinity.restype = ctypes.c_bool

            hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()
            gwl_exstyle = -20
            ws_ex_layered = 0x00080000
            ws_ex_transparent = 0x00000020
            ws_ex_noactivate = 0x08000000
            ws_ex_toolwindow = 0x00000080
            ws_ex_appwindow = 0x00040000
            style = user32.GetWindowLongW(hwnd, gwl_exstyle)
            # A normal app-window bit makes the overlay selectable in OBS Window
            # Capture; the tool-window bit hides it from some capture pickers.
            if enabled:
                new_style = style | ws_ex_layered | ws_ex_transparent | ws_ex_noactivate
            else:
                new_style = (style | ws_ex_layered) & ~ws_ex_transparent & ~ws_ex_noactivate
            if self.obs_mode:
                new_style = (new_style | ws_ex_appwindow) & ~ws_ex_toolwindow
            else:
                new_style = (new_style | ws_ex_toolwindow) & ~ws_ex_appwindow
            user32.SetWindowLongW(hwnd, gwl_exstyle, new_style)
            if self.obs_mode:
                # Explicitly opt into capture (WDA_NONE) for OBS/Game Bar.
                user32.SetWindowDisplayAffinity(hwnd, 0)
        except Exception:
            pass

    def _locate_game_window(self, force: bool = False):
        """Return the game client-area origin, re-scanning for the window when needed."""
        if not self.cfg.get("follow_game_window", True):
            return None

        now = time.perf_counter()
        hwnd = self._game_hwnd
        if hwnd:
            origin = get_window_client_origin(hwnd)
            if origin is not None:
                self._game_origin = origin
                return origin

        if not force and (now - self._last_game_scan) < 1.0:
            return None

        found = find_game_window()
        self._last_game_scan = now
        if not found:
            self._game_hwnd = None
            self._game_origin = None
            return None

        hwnd = found[0]
        self._game_hwnd = hwnd
        self._game_origin = get_window_client_origin(hwnd)
        return self._game_origin

    def _sync_game_position(self):
        """Keep the overlay at the same offset inside the game's client area."""
        if self.root is None or self._drag_mode is not None:
            return
        origin = self._locate_game_window()
        if origin is None:
            return

        offset_x = self.cfg.get("offset_x")
        offset_y = self.cfg.get("offset_y")
        if offset_x is None or offset_y is None:
            # First time we can see the game: remember where the overlay currently is.
            self.cfg["offset_x"] = int(self.root.winfo_x()) - origin[0]
            self.cfg["offset_y"] = int(self.root.winfo_y()) - origin[1]
            self._save_config()
            return

        target_x = origin[0] + int(offset_x)
        target_y = origin[1] + int(offset_y)
        if abs(self.root.winfo_x() - target_x) >= 1 or abs(self.root.winfo_y() - target_y) >= 1:
            self.root.geometry(f"+{target_x}+{target_y}")
            self._sync_hint_win_pos()

    def _sync_hint_win_pos(self):
        if self.hint_win is not None and self.root is not None and self.edit_mode:
            rx = self.root.winfo_x()
            ry = self.root.winfo_y()
            hy = max(0, ry - 26)
            self.hint_win.geometry(f"+{rx}+{hy}")

    def _resolve_icon_path(self, suit_id: str, set_name: str):
        if not self.file_index:
            self._index_icon_files()

        info = DISC_SET_MAP.get(suit_id, {})
        icon_stem = info.get("icon", "")
        clean_title = re.sub(r"\s*\([24]pc\)\s*", "", set_name, flags=re.IGNORECASE).strip()

        for stem in (icon_stem, f"Suit{clean_title}", clean_title, suit_id, f"Suit_Ability_{suit_id}"):
            if not stem:
                continue
            if stem.lower() in self.file_index:
                return self.file_index[stem.lower()]
            nk = norm_filename_key(stem)
            if nk in self.file_index:
                return self.file_index[nk]
        return None

    def _load_disc_icon(self, suit_id: str, set_name: str, px_size: int):
        cache_key = (suit_id, px_size)
        if cache_key in self.icon_cache:
            return self.icon_cache[cache_key]

        if HAS_PIL:
            if suit_id not in self.raw_pil_cache:
                fpath = self._resolve_icon_path(suit_id, set_name)
                if fpath and os.path.isfile(fpath):
                    try:
                        self.raw_pil_cache[suit_id] = Image.open(fpath).convert("RGBA")
                    except Exception:
                        self.raw_pil_cache[suit_id] = None
                else:
                    self.raw_pil_cache[suit_id] = None

            raw_img = self.raw_pil_cache.get(suit_id)
            if raw_img is not None:
                try:
                    resized = raw_img.resize((px_size, px_size), Image.Resampling.LANCZOS)
                    photo = ImageTk.PhotoImage(resized)
                    self.icon_cache[cache_key] = photo
                    return photo
                except Exception:
                    pass
        else:
            fpath = self._resolve_icon_path(suit_id, set_name)
            if fpath and os.path.isfile(fpath):
                if fpath.lower().endswith(".png"):
                    try:
                        photo = tk.PhotoImage(file=fpath)
                        w = photo.width()
                        if w > px_size:
                            factor = max(1, int(round(w / px_size)))
                            photo = photo.subsample(factor, factor)
                        self.icon_cache[cache_key] = photo
                        return photo
                    except Exception:
                        pass
                elif fpath.lower().endswith(".webp") and not self.warned_webp:
                    self.warned_webp = True
                    print("[!] Install Pillow ('pip install pillow') to load .webp Drive Disc icons!", flush=True)

        self.icon_cache[cache_key] = None
        return None

    def _load_shadow_icon(self, suit_id: str, set_name: str, px_size: int):
        """Greyed/dimmed icon used for the post-buff cooldown shadow."""
        cache_key = (suit_id, px_size, "shadow")
        if cache_key in self.icon_cache:
            return self.icon_cache[cache_key]
        if not HAS_PIL:
            return None

        self._load_disc_icon(suit_id, set_name, px_size)
        raw_img = self.raw_pil_cache.get(suit_id)
        if raw_img is None:
            return None
        try:
            grey = ImageOps.grayscale(raw_img).convert("RGB")
            grey = ImageEnhance.Brightness(grey).enhance(0.52)
            shadow = grey.convert("RGBA")
            shadow.putalpha(raw_img.getchannel("A").point(lambda a: int(a * 0.82)))
            shadow = shadow.resize((px_size, px_size), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(shadow)
            self.icon_cache[cache_key] = photo
            return photo
        except Exception:
            return None

    def _run_gui(self):
        try:
            self.root = tk.Tk()
            self.root.title("ZZZ Drive Disc Overlay" + (" (OBS)" if self.obs_mode else ""))
            self.root.overrideredirect(True)
            self.root.wm_attributes("-topmost", True)
            if not self.obs_bg:
                self.root.wm_attributes("-transparentcolor", self.TRANSPARENT_KEY)
            self.root.configure(bg=self.TRANSPARENT_KEY)

            screen_w = self.root.winfo_screenwidth()
            x_pos = self.cfg.get("x")
            if x_pos is None:
                x_pos = (screen_w - 340) if self.default_pos == "top-right" else 30
            y_pos = self.cfg.get("y", 60)
            if y_pos is None:
                y_pos = 60

            game_origin = self._locate_game_window(force=True)
            if game_origin is not None:
                offset_x = self.cfg.get("offset_x")
                offset_y = self.cfg.get("offset_y")
                if offset_x is not None and offset_y is not None:
                    x_pos = game_origin[0] + int(offset_x)
                    y_pos = game_origin[1] + int(offset_y)
                else:
                    # Migrate old absolute coordinates into game-relative offsets.
                    self.cfg["offset_x"] = int(x_pos) - game_origin[0]
                    self.cfg["offset_y"] = int(y_pos) - game_origin[1]

            self.root.geometry(f"+{int(x_pos)}+{int(y_pos)}")

            self.container = tk.Frame(self.root, bg=self.TRANSPARENT_KEY, bd=0, highlightthickness=0)
            self.container.pack(fill="both", expand=True)

            # Separate floating Toplevel for the F8 edit banner so self.root NEVER shifts or jolts!
            self.hint_win = tk.Toplevel(self.root)
            self.hint_win.overrideredirect(True)
            self.hint_win.wm_attributes("-topmost", True)
            self.hint_win.configure(bg="#181A22")
            hint_lbl = tk.Label(
                self.hint_win,
                text="UNLOCKED (F8 Lock) • Drag Disc: Move • Drag Corner ◢ / Right-Drag: Resize • Dbl-Click: Row/Col",
                bg="#181A22",
                fg="#FAB005",
                font=("Segoe UI", 8, "bold"),
                padx=6,
                pady=2,
            )
            hint_lbl.pack()
            self.hint_win.withdraw()

            self.root.update_idletasks()
            if game_origin is not None:
                self._save_config()
            self._set_window_click_through(self.root, True)
            self._set_window_click_through(self.hint_win, True)
            self.root.after(40, self._tick)
            self.root.mainloop()
        except Exception as e:
            print(f"[!] Overlay GUI could not start: {e}", flush=True)

    def _bind_interactive_events(self, widget):
        widget.bind("<ButtonPress-1>", self._on_left_down)
        widget.bind("<B1-Motion>", self._on_left_drag)
        widget.bind("<ButtonRelease-1>", self._on_mouse_up)
        widget.bind("<ButtonPress-3>", self._on_right_down)
        widget.bind("<B3-Motion>", self._on_right_drag)
        widget.bind("<ButtonRelease-3>", self._on_mouse_up)
        widget.bind("<MouseWheel>", self._on_mouse_wheel)
        widget.bind("<Double-Button-1>", self._on_double_click)

    def _on_left_down(self, event):
        if not self.edit_mode:
            return
        w = event.widget.winfo_width()
        h = event.widget.winfo_height()
        if event.x >= w - 22 and event.y >= h - 22:
            self._drag_mode = "resize"
            self._drag_start = (event.x_root, event.y_root, self.cfg["icon_size"], 0)
        else:
            self._drag_mode = "move"
            self._drag_start = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y(), 0, 0)

    def _on_left_drag(self, event):
        if not self.edit_mode or not self._drag_mode:
            return
        if self._drag_mode == "move":
            new_x = event.x_root - self._drag_start[0]
            new_y = event.y_root - self._drag_start[1]
            self.root.geometry(f"+{new_x}+{new_y}")
            self._sync_hint_win_pos()
        elif self._drag_mode == "resize":
            delta = max(event.x_root - self._drag_start[0], event.y_root - self._drag_start[1])
            new_size = max(36, min(220, int(self._drag_start[2] + delta)))
            if abs(new_size - self.cfg["icon_size"]) >= 2:
                self.cfg["icon_size"] = new_size
                self._rebuild_all_cards()

    def _on_right_down(self, event):
        if not self.edit_mode:
            return
        self._drag_mode = "resize"
        self._drag_start = (event.x_root, event.y_root, self.cfg["icon_size"], 0)

    def _on_right_drag(self, event):
        if not self.edit_mode or self._drag_mode != "resize":
            return
        delta = max(event.x_root - self._drag_start[0], event.y_root - self._drag_start[1])
        new_size = max(36, min(220, int(self._drag_start[2] + delta)))
        if abs(new_size - self.cfg["icon_size"]) >= 2:
            self.cfg["icon_size"] = new_size
            self._rebuild_all_cards()

    def _on_mouse_up(self, _event):
        if self.edit_mode and self._drag_mode:
            self._drag_mode = None
            self._save_config()

    def _on_mouse_wheel(self, event):
        if not self.edit_mode:
            return
        step = 6 if event.delta > 0 else -6
        new_size = max(36, min(220, self.cfg["icon_size"] + step))
        if new_size != self.cfg["icon_size"]:
            self.cfg["icon_size"] = new_size
            self._rebuild_all_cards()
            self._save_config()

    def _on_double_click(self, _event):
        if not self.edit_mode:
            return
        self.cfg["layout"] = "vertical" if self.cfg.get("layout") == "horizontal" else "horizontal"
        self._rebuild_all_cards()
        self._save_config()

    def _toggle_edit_mode(self):
        self.edit_mode = not self.edit_mode
        if self.edit_mode:
            self._set_window_click_through(self.root, False)
            self._sync_hint_win_pos()
            self.hint_win.deiconify()
            if not self.cards:
                now = self._game_now()
                self._create_or_update_card(
                    ("__preview_1", "50432800"), "50432800", "Astral Voice (4pc)", "Sigrid",
                    get_character_color("Sigrid"), 2, 15.0, preview=True, custom_expiries=[now + 8.5, now + 14.2]
                )
                self._create_or_update_card(
                    ("__preview_2", "50432800"), "50432800", "Astral Voice (4pc)", "Norma",
                    get_character_color("Norma"), 3, 15.0, preview=True, custom_expiries=[now + 6.0, now + 11.0, now + 15.0]
                )
                self._create_or_update_card(
                    ("__preview_3", "50433400"), "50433400", "Moonlight Lullaby (4pc)", "Rina",
                    get_character_color("Rina"), 1, 25.0, preview=True, custom_expiries=[now + 21.5]
                )
            else:
                self._rebuild_all_cards()
        else:
            self.hint_win.withdraw()
            for k in [k for k, v in self.cards.items() if v.get("preview")]:
                self.cards.pop(k)["canvas"].destroy()
            self._rebuild_all_cards()
            self._set_window_click_through(self.root, True)
            self._save_config()

    def _rebuild_all_cards(self):
        snapshot = [
            (
                gk, c["suit_id"], c["set_name"], c["holder_name"], c["holder_color"],
                c["stacks"], c["duration_s"], list(c["stack_expiries"]), c.get("preview", False),
                c.get("effect_key", DEFAULT_EFFECT_KEY), c.get("effect_label", ""),
                c.get("shadow", False), c.get("shadow_until"), c.get("shadow_total", 0.0), c.get("shadow_s", 0.0),
            )
            for gk, c in self.cards.items()
        ]
        for c in self.cards.values():
            c["canvas"].destroy()
        self.cards.clear()
        for gk, suit_id, set_name, holder_name, holder_color, stacks, duration_s, expiries, preview, effect_key, effect_label, shadow, shadow_until, shadow_total, shadow_s in snapshot:
            self._create_or_update_card(
                gk, suit_id, set_name, holder_name, holder_color, stacks, duration_s,
                preview=preview, add_stack=not shadow, custom_expiries=expiries,
                effect_key=effect_key, effect_label=effect_label,
            )
            if shadow and gk in self.cards:
                new_card = self.cards[gk]
                new_card["shadow_s"] = shadow_s
                self._enter_card_shadow(new_card, self._game_now())
                new_card["shadow_until"] = shadow_until
                new_card["shadow_total"] = shadow_total or shadow_s

    def _create_outlined_text(self, canvas: tk.Canvas, x: int, y: int, text: str, fill: str, font, outline: str = TEXT_OUTLINE):
        """Draws transparent-background text with a 1px dark outline so it is readable without a box."""
        shadow_ids = [
            canvas.create_text(x - 1, y, text=text, fill=outline, font=font),
            canvas.create_text(x + 1, y, text=text, fill=outline, font=font),
            canvas.create_text(x, y - 1, text=text, fill=outline, font=font),
            canvas.create_text(x, y + 1, text=text, fill=outline, font=font),
        ]
        main_id = canvas.create_text(x, y, text=text, fill=fill, font=font)
        return (main_id, shadow_ids)

    def _update_outlined_text(self, canvas: tk.Canvas, text_bundle, new_text: str = None, new_fill: str = None):
        main_id, shadow_ids = text_bundle
        if new_text is not None:
            for sid in shadow_ids:
                canvas.itemconfigure(sid, text=new_text)
            canvas.itemconfigure(main_id, text=new_text)
        if new_fill is not None:
            canvas.itemconfigure(main_id, fill=new_fill)

    def _update_stack_badge(self, card: dict, stacks: int):
        canvas = card["canvas"]
        if stacks > 1:
            canvas.itemconfigure(card["badge_oval"], state="normal")
            canvas.itemconfigure(card["badge_text"], state="normal", text=str(stacks))
        else:
            canvas.itemconfigure(card["badge_oval"], state="hidden")
            canvas.itemconfigure(card["badge_text"], state="hidden")

    def _enter_card_shadow(self, card: dict, now: float):
        """Grey the card out and count down its post-buff downtime."""
        if card.get("shadow") or card.get("shadow_s", 0.0) <= 0:
            return
        shadow_s = float(card["shadow_s"])
        card["shadow"] = True
        card["shadow_total"] = shadow_s
        card["shadow_until"] = now + shadow_s
        card["stack_expiries"] = []
        card["stacks"] = 1

        canvas = card["canvas"]
        canvas.itemconfigure(card["badge_oval"], state="hidden")
        canvas.itemconfigure(card["badge_text"], state="hidden")
        canvas.itemconfigure(card["ring_arc"], outline="#565C68", extent=-360)

        shadow_photo = self._load_shadow_icon(card["suit_id"], card["set_name"], card.get("icon_px", 76))
        if shadow_photo is not None and card.get("icon_id") is not None:
            canvas.itemconfigure(card["icon_id"], image=shadow_photo)
        elif card.get("icon_id") is not None:
            # Pillow-less fallback: a stippled dark overlay reads as greyed out.
            if card.get("shadow_overlay") is None:
                cx, cy, r = card["icon_cx"], card["icon_cy"], card["icon_r"]
                card["shadow_overlay"] = canvas.create_rectangle(
                    cx - r, cy - r, cx + r, cy + r,
                    fill="#1A1D24", outline="", stipple="gray50",
                )
            canvas.itemconfigure(card["shadow_overlay"], state="normal")

        self._update_outlined_text(card["canvas"], card["time_text"], new_text=f"{shadow_s:.1f}s", new_fill="#9AA0AA")
        self._update_outlined_text(card["canvas"], card["holder_text"], new_fill="#7F858F")

    def _restore_card_from_shadow(self, card: dict, now: float):
        if not card.get("shadow"):
            return
        card["shadow"] = False
        card["shadow_until"] = None
        card["shadow_total"] = 0.0
        canvas = card["canvas"]
        canvas.itemconfigure(card["ring_arc"], outline=card.get("ring_color", "#FAB005"))
        if card.get("shadow_overlay") is not None:
            canvas.itemconfigure(card["shadow_overlay"], state="hidden")
        if card.get("icon_id") is not None:
            photo = self._load_disc_icon(card["suit_id"], card["set_name"], card.get("icon_px", 76))
            if photo is not None:
                canvas.itemconfigure(card["icon_id"], image=photo)
        self._update_outlined_text(canvas, card["time_text"], new_fill="#FFFFFF")
        self._update_outlined_text(canvas, card["holder_text"], new_fill=card.get("holder_color", "#FFFFFF"))

    def _create_or_update_card(
        self,
        group_key,
        suit_id: str,
        set_name: str,
        holder_name: str,
        holder_color: str,
        stacks: int,
        duration_s: float,
        preview: bool = False,
        add_stack: bool = True,
        custom_expiries: list = None,
        effect_key: str = DEFAULT_EFFECT_KEY,
        effect_label: str = "",
    ):
        now = self._game_now()
        effect_cfg, info = get_effect_config(suit_id, effect_key)
        accent = info.get("color", "#FAB005")
        max_st = effect_cfg.get("max_stacks", 1)
        no_auto_expire = effect_cfg.get("no_auto_expire", False)
        refresh_all = effect_cfg.get("refresh_all", False)
        decay_one = effect_cfg.get("decay_one", False)
        shadow_s = float(effect_cfg.get("shadow_s", 0.0) or 0.0)
        clean_title = re.sub(r"\s*\([24]pc\)\s*", "", set_name, flags=re.IGNORECASE).strip()
        dur = duration_s if duration_s > 0 else (effect_cfg.get("dur_s", 15.0) or 15.0)
        display_holder = format_holder_label(holder_name, effect_label)

        if group_key in self.cards:
            card = self.cards[group_key]
            if card.get("shadow"):
                self._restore_card_from_shadow(card, now)
            card["duration_s"] = dur
            card["decay_one"] = decay_one
            card["holder_name"] = holder_name
            card["holder_color"] = holder_color
            card["effect_label"] = effect_label
            self._update_outlined_text(card["canvas"], card["holder_text"], new_text=display_holder, new_fill=holder_color)

            # Purge any already-expired stacks
            if not no_auto_expire:
                card["stack_expiries"] = [e for e in card["stack_expiries"] if e > now]

            if max_st <= 1:
                if add_stack:
                    card["stack_expiries"] = [now + dur]
            elif refresh_all:
                if add_stack:
                    # Astral Voice and similar effects say "repeated triggers reset
                    # the duration": every stack gets a fresh full-duration timer.
                    wanted = min(max_st, max(1, len(card["stack_expiries"]), int(stacks)))
                    card["stack_expiries"] = [now + dur] * wanted
            else:
                if add_stack:
                    if len(card["stack_expiries"]) < max_st:
                        card["stack_expiries"].append(now + dur)
                    else:
                        # At max stacks: replace the oldest stack with a fresh timer
                        card["stack_expiries"].pop(0)
                        card["stack_expiries"].append(now + dur)
                    card["stack_expiries"].sort()

                # Reconcile if explicit stack count is higher than our timer list
                while len(card["stack_expiries"]) < min(max_st, stacks):
                    card["stack_expiries"].append(now + dur)

            card["stacks"] = len(card["stack_expiries"]) if max_st > 1 else 1
            self._update_stack_badge(card, card["stacks"])
            return

        if custom_expiries is not None:
            expiries = list(custom_expiries)
        else:
            cnt = min(max_st, max(1, stacks)) if max_st > 1 else 1
            expiries = [now + dur for _ in range(cnt)]

        px = self.cfg.get("icon_size", 76)
        pad = 6
        timer_font_sz = max(9, int(round(px * 0.155)))
        name_font_sz = max(8, int(round(px * 0.14)))
        footer_h = max(30, int(round(px * 0.44)))
        cw = max(px + pad * 2, int(round(px * 1.18)))
        ch = px + pad + footer_h + 4

        # Use highlightthickness=0 always so unlocking with F8 never shifts card dimensions by 1px!
        pack_side = "left" if self.cfg.get("layout", "horizontal") == "horizontal" else "top"
        canvas = tk.Canvas(
            self.container,
            width=cw,
            height=ch,
            bg=self.TRANSPARENT_KEY,
            highlightthickness=0,
            bd=0,
            cursor="fleur" if self.edit_mode else "arrow",
        )
        canvas.pack(side=pack_side, padx=4, pady=4)
        self._bind_interactive_events(canvas)

        cx = cw // 2
        cy = pad + px // 2
        r = px // 2

        # Dark backing circle & progress arc around the disc
        canvas.create_oval(cx - r - 2, cy - r - 2, cx + r + 2, cy + r + 2, fill="#111217", outline="#282C37", width=2)
        ring_arc = canvas.create_arc(
            cx - r - 2,
            cy - r - 2,
            cx + r + 2,
            cy + r + 2,
            start=90,
            extent=-360,
            style="arc",
            outline=accent,
            width=3,
        )

        # Drive Disc Image
        icon_id = None
        photo = self._load_disc_icon(suit_id, set_name, px)
        if photo is not None:
            icon_id = canvas.create_image(cx, cy, image=photo)
        else:
            canvas.create_oval(cx - r + 2, cy - r + 2, cx + r - 2, cy + r - 2, fill="#22252E", outline=accent, width=2)
            initials = "".join(w[0].upper() for w in clean_title.split()[:2])
            canvas.create_text(cx, cy, text=initials, fill="#FFFFFF", font=("Segoe UI", max(8, px // 5), "bold"))

        # Small Stack Circle on the BOTTOM-LEFT of the disc (only shown when stacks > 1)
        badge_r = max(10, int(round(px * 0.19)))
        bx = cx - r + badge_r + 1
        by = cy + r - badge_r - 1
        badge_oval = canvas.create_oval(
            bx - badge_r,
            by - badge_r,
            bx + badge_r,
            by + badge_r,
            fill=self.BADGE_BG,
            outline=accent,
            width=2,
        )
        badge_font_sz = max(8, int(round(badge_r * 0.95)))
        badge_text = canvas.create_text(
            bx,
            by,
            text=str(len(expiries)),
            fill="#FFFFFF",
            font=("Segoe UI", badge_font_sz, "bold"),
        )

        # Transparent Timer & Attribute-Colored Character Name directly below the disc (NO BOX)
        top_text_y = pad + px + int(footer_h * 0.30)
        bot_text_y = pad + px + int(footer_h * 0.74)

        time_text = self._create_outlined_text(
            canvas, cx, top_text_y, f"{dur:.1f}s", "#FFFFFF", ("Consolas", timer_font_sz, "bold")
        )
        holder_text = self._create_outlined_text(
            canvas, cx, bot_text_y, display_holder, holder_color, ("Segoe UI", name_font_sz, "bold")
        )

        # Dashed edit border + corner resize grip drawn inside canvas when unlocked (zero layout shift!)
        if self.edit_mode:
            canvas.create_rectangle(1, 1, cw - 2, ch - 2, outline="#FAB005", width=1, dash=(3, 3))
            canvas.create_text(
                cw - 2,
                ch - 1,
                text="◢",
                anchor="se",
                fill="#FAB005",
                font=("Segoe UI", 10, "bold"),
            )

        cur_st = len(expiries) if max_st > 1 else 1
        card = {
            "canvas": canvas,
            "suit_id": suit_id,
            "set_name": set_name,
            "holder_name": holder_name,
            "holder_color": holder_color,
            "ring_arc": ring_arc,
            "ring_color": accent,
            "icon_id": icon_id,
            "icon_cx": cx,
            "icon_cy": cy,
            "icon_r": r,
            "icon_px": px,
            "shadow_overlay": None,
            "shadow": False,
            "shadow_until": None,
            "shadow_total": 0.0,
            "shadow_s": shadow_s,
            "badge_oval": badge_oval,
            "badge_text": badge_text,
            "time_text": time_text,
            "holder_text": holder_text,
            "stack_expiries": expiries,
            "duration_s": dur,
            "stacks": cur_st,
            "no_auto_expire": no_auto_expire,
            "decay_one": decay_one,
            "effect_key": effect_key,
            "effect_label": effect_label,
            "preview": preview,
        }
        self._update_stack_badge(card, cur_st)
        self.cards[group_key] = card

    def _tick(self):
        try:
            self._sync_game_position()
        except Exception:
            pass

        try:
            f8_down = bool(ctypes.windll.user32.GetAsyncKeyState(self.VK_F8) & 0x8000)
            if f8_down and not self.f8_was_down:
                self._toggle_edit_mode()
            self.f8_was_down = f8_down
        except Exception:
            pass

        real_now = time.perf_counter()

        try:
            while True:
                cmd = self.cmd_queue.get_nowait()
                action = cmd[0]
                if action == "upsert":
                    _, group_key, suit_id, set_name, holder_name, holder_color, stacks, duration_s, add_stack, effect_key, effect_label = cmd
                    for k in [k for k, v in self.cards.items() if v.get("preview")]:
                        self.cards.pop(k)["canvas"].destroy()
                    self._create_or_update_card(
                        group_key, suit_id, set_name, holder_name, holder_color, stacks, duration_s,
                        add_stack=add_stack, effect_key=effect_key, effect_label=effect_label,
                    )
                elif action == "pop_stack":
                    _, group_key, expected_stacks = cmd
                    card = self.cards.get(group_key)
                    if card and card["stack_expiries"]:
                        if expected_stacks is not None:
                            while len(card["stack_expiries"]) > expected_stacks and len(card["stack_expiries"]) > 1:
                                card["stack_expiries"].pop(0)
                        elif len(card["stack_expiries"]) > 1:
                            card["stack_expiries"].pop(0)
                        if card.get("decay_one") and card["stack_expiries"]:
                            # Bunny in Wonderland refreshes its 25s timer when a
                            # stack decays, so keep the remaining stacks alive.
                            refreshed = self._game_now(real_now) + card["duration_s"]
                            card["stack_expiries"] = [refreshed] * len(card["stack_expiries"])
                        card["stacks"] = len(card["stack_expiries"])
                        self._update_stack_badge(card, card["stacks"])
                elif action == "rename":
                    _, group_key, new_holder_name, new_holder_color = cmd
                    card = self.cards.get(group_key)
                    if card:
                        card["holder_name"] = new_holder_name
                        card["holder_color"] = new_holder_color
                        self._update_outlined_text(
                            card["canvas"], card["holder_text"],
                            new_text=format_holder_label(new_holder_name, card.get("effect_label", "")),
                            new_fill=new_holder_color,
                        )
                elif action == "remove":
                    _, group_key = cmd
                    card = self.cards.get(group_key)
                    if card:
                        if card.get("shadow_s", 0.0) > 0:
                            self._enter_card_shadow(card, self._game_now(real_now))
                        else:
                            self.cards.pop(group_key, None)
                            card["canvas"].destroy()
                elif action == "time_scale":
                    _, scale = cmd
                    self._apply_time_scale(scale, real_now)
                elif action == "clear":
                    for k in [k for k, v in self.cards.items() if not v.get("preview")]:
                        self.cards.pop(k)["canvas"].destroy()
        except queue.Empty:
            pass

        self._advance_clock(real_now)
        now = self._game_now(real_now)

        for group_key, card in list(self.cards.items()):
            if card.get("shadow"):
                remaining = max(0.0, (card.get("shadow_until") or now) - now)
                if remaining <= 0:
                    card["canvas"].destroy()
                    del self.cards[group_key]
                    continue
                self._update_outlined_text(card["canvas"], card["time_text"], new_text=f"{remaining:.1f}s")
                total = card.get("shadow_total") or 1.0
                frac = min(1.0, remaining / total) if total > 0 else 0.0
                card["canvas"].itemconfigure(card["ring_arc"], extent=-360.0 * frac)
                continue
            if card.get("preview"):
                # Loop preview timers smoothly while unlocked
                if card["stack_expiries"] and now >= card["stack_expiries"][0]:
                    card["stack_expiries"].pop(0)
                    card["stack_expiries"].append(now + card["duration_s"])
                    card["stack_expiries"].sort()
            elif card.get("decay_one"):
                # One stack falls off at a time; the remaining stacks get a
                # fresh full-duration timer ("duration refreshes when decayed").
                decayed_any = False
                while card["stack_expiries"] and now >= card["stack_expiries"][0]:
                    decay_at = card["stack_expiries"].pop(0)
                    decayed_any = True
                    if card["stack_expiries"]:
                        card["stack_expiries"] = [decay_at + card["duration_s"]] * len(card["stack_expiries"])

                if not card["stack_expiries"]:
                    if card.get("shadow_s", 0.0) > 0:
                        self._enter_card_shadow(card, now)
                        continue
                    card["canvas"].destroy()
                    del self.cards[group_key]
                    continue

                if decayed_any:
                    card["stacks"] = len(card["stack_expiries"])
                    self._update_stack_badge(card, card["stacks"])
            elif not card.get("no_auto_expire", False):
                # Pop any stacks whose individual duration has run out
                expired_any = False
                while card["stack_expiries"] and now >= card["stack_expiries"][0]:
                    card["stack_expiries"].pop(0)
                    expired_any = True

                # If all stacks ran out, remove the disc from the overlay immediately!
                if not card["stack_expiries"]:
                    if card.get("shadow_s", 0.0) > 0:
                        self._enter_card_shadow(card, now)
                        continue
                    card["canvas"].destroy()
                    del self.cards[group_key]
                    continue

                # If 1 stack ran out but others remain, reduce stack badge by 1;
                # stack_expiries[0] is now automatically the 2nd stack (closest to running out)!
                if expired_any:
                    card["stacks"] = len(card["stack_expiries"])
                    self._update_stack_badge(card, card["stacks"])

            rem = max(0.0, card["stack_expiries"][0] - now) if card["stack_expiries"] else 0.0
            self._update_outlined_text(card["canvas"], card["time_text"], new_text=f"{rem:.1f}s")
            frac = min(1.0, rem / card["duration_s"]) if card["duration_s"] > 0 else 1.0
            card["canvas"].itemconfigure(card["ring_arc"], extent=-360.0 * frac)

        if self.root is not None:
            self.root.after(40, self._tick)


class TailReader:
    def __init__(self, path: str):
        self.path = path
        self.offset = 0
        self.header = None

    def read_new_lines(self):
        if not os.path.isfile(self.path):
            return []
        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(self.offset)
                chunk = f.read()
                if not chunk:
                    return []
                last_nl = chunk.rfind("\n")
                if last_nl == -1:
                    return []
                self.offset += len(chunk[: last_nl + 1].encode("utf-8", errors="replace"))
                lines = chunk[:last_nl].splitlines()
        except OSError:
            return []

        rows = []
        for line in lines:
            line = line.strip("\r\n")
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if self.header is None:
                self.header = {name: i for i, name in enumerate(parts)}
                continue
            rows.append((self.header, parts))
        return rows


class BattleSession:
    def __init__(self, battle_dir: str, live_print: bool = True, include_passive: bool = False, overlay: DiscOverlayHUD = None):
        self.battle_dir = battle_dir
        self.live_print = live_print
        self.include_passive = include_passive
        self.overlay = overlay

        self.state_tail = TailReader(os.path.join(battle_dir, "state.tsv"))
        self.hits_tail = TailReader(os.path.join(battle_dir, "hits.tsv"))
        self.ts_tail = TailReader(os.path.join(battle_dir, "timescale.tsv"))
        self.events_tail = TailReader(os.path.join(battle_dir, "events.tsv"))
        self.res_tail = None

        self.entity_votes = {}
        self.entity_names = {}
        self.entity_attrs = {}       # ptr -> detected Attribute string
        self.instance_ability = {}
        self.instance_meta = {}
        self.stat_ptr_holder = {}
        self.slot_owner = {}

        self.last_suit_attach_ms = {}  # suit_id -> (t_ms, holder_key)
        self.holder_suits = {}         # holder ptr -> {suit_id, ...}
        self.ex_owner_suits = {}       # wearer ptr -> {teamwide suit_id, ...}
        self.active_groups = {}
        self.pending_detaches = {}
        self.buff_stats = {}
        self.detected_suits = set()
        self.pending_astral_qa = []

        self.hit_records = []
        self.ts_steps = []
        self.ts_removed = 0.0
        self.ts_held_at = None
        self.ts_last = None
        self.overlay_time_scale = None
        self.first_event_ms = None
        self.last_event_ms = 0.0
        self.last_wall_t = None

    def _find_result_file(self):
        if self.res_tail is not None:
            return
        try:
            for fname in os.listdir(self.battle_dir):
                if fname.startswith("damage-result-") and fname.endswith(".tsv"):
                    self.res_tail = TailReader(os.path.join(self.battle_dir, fname))
                    break
        except OSError:
            pass

    def _vote_entity(self, ptr: str, name: str, weight: int = 1):
        if not ptr or not name:
            return
        ptr = ptr.lower()
        old_name = self.entity_names.get(ptr)
        bucket = self.entity_votes.setdefault(ptr, {})
        bucket[name] = bucket.get(name, 0) + weight
        new_name = max(bucket.items(), key=lambda x: x[1])[0]
        self.entity_names[ptr] = new_name

        if new_name != old_name and self.overlay is not None:
            color = self.fmt_entity_color(ptr)
            for (h_key, suit_id, effect_key), grp in list(self.active_groups.items()):
                if h_key == ptr or grp.get("caster_ptr") == ptr:
                    disp_name = self.fmt_holder_display(h_key, grp.get("caster_ptr"))
                    disp_col = self.fmt_holder_color(h_key, grp.get("caster_ptr"))
                    self.overlay.update_holder_info((h_key, suit_id, effect_key), disp_name, disp_col)

    def _record_entity_attr(self, ptr: str, attr: str):
        if not ptr or not attr or attr not in ATTRIBUTE_COLORS:
            return
        ptr = ptr.lower()
        if self.entity_attrs.get(ptr) != attr:
            self.entity_attrs[ptr] = attr
            if self.overlay is not None:
                for (h_key, suit_id, effect_key), grp in list(self.active_groups.items()):
                    if h_key == ptr or grp.get("caster_ptr") == ptr:
                        disp_name = self.fmt_holder_display(h_key, grp.get("caster_ptr"))
                        disp_col = self.fmt_holder_color(h_key, grp.get("caster_ptr"))
                        self.overlay.update_holder_info((h_key, suit_id, effect_key), disp_name, disp_col)

    def fmt_entity(self, ptr: str) -> str:
        if ptr == "TEAM":
            return "Team"
        if not ptr:
            return "Squad/Unknown"
        p = ptr.lower()
        if p in self.entity_names:
            return self.entity_names[p]
        return f"Entity({p[-5:]})"

    def fmt_entity_color(self, ptr: str) -> str:
        if ptr == "TEAM" or not ptr:
            return ATTRIBUTE_COLORS["Team"]
        p = ptr.lower()
        c_name = self.entity_names.get(p, "")
        det_attr = self.entity_attrs.get(p)
        return get_character_color(c_name, det_attr)

    def fmt_holder_display(self, holder_key: str, caster_ptr: str = "") -> str:
        # Team-wide buffs are active on the whole squad, not just on the
        # character who happened to trigger them.
        if holder_key == "TEAM":
            return "Team"
        return self.fmt_entity(holder_key)

    def fmt_holder_color(self, holder_key: str, caster_ptr: str = "") -> str:
        if holder_key == "TEAM":
            return ATTRIBUTE_COLORS["Team"]
        return self.fmt_entity_color(holder_key)

    def resolve_holder_key(self, suit_id: str, raw_holder_ptr: str) -> str:
        if DISC_SET_MAP.get(suit_id, {}).get("teamwide", False):
            return "TEAM"
        return raw_holder_ptr

    def game_sec(self, ms: float) -> float:
        if not self.ts_steps:
            base = self.first_event_ms if self.first_event_ms is not None else ms
            return max(0.0, (ms - base) / 1000.0)
        i = len(self.ts_steps) - 1
        while i > 0 and self.ts_steps[i][0] > ms:
            i -= 1
        t_a, world_a, scale_a = self.ts_steps[i]
        if i + 1 < len(self.ts_steps):
            t_b, world_b, _ = self.ts_steps[i + 1]
            if t_b > t_a and ms >= t_a:
                return world_a + (world_b - world_a) * (ms - t_a) / (t_b - t_a)
        return world_a + scale_a * (ms - t_a) / 1000.0

    def _print_live_event(
        self,
        t_ms: float,
        tag: str,
        holder_key: str,
        caster_ptr: str,
        suit_id: str,
        set_name: str,
        stacks: int,
        dur_text: str,
        add_stack: bool = True,
        effect_key: str = DEFAULT_EFFECT_KEY,
        effect_label: str = "",
    ):
        holder_name = self.fmt_holder_display(holder_key, caster_ptr)
        holder_color = self.fmt_holder_color(holder_key, caster_ptr)
        display_set = f"{set_name} [{effect_label}]" if effect_label else set_name
        if self.live_print:
            t_s = self.game_sec(t_ms)
            stack_col = f"x{stacks}" if stacks > 1 else ""
            print(
                f"  [{t_s:6.2f}s] [{tag:<8}] {holder_name:<16} | {display_set:<30} | {stack_col:<5} | {dur_text}",
                flush=True,
            )

        if self.overlay is not None:
            group_key = (holder_key, suit_id, effect_key)
            if tag in ("+START", "~REFRESH"):
                effect_cfg, _ = get_effect_config(suit_id, effect_key)
                dur_s = effect_cfg.get("dur_s", 15.0)
                self.overlay.notify_buff(
                    group_key, suit_id, set_name, holder_name, holder_color, stacks, dur_s,
                    add_stack=add_stack, effect_key=effect_key, effect_label=effect_label,
                )
            elif tag == "-STACK":
                self.overlay.pop_stack(group_key, expected_stacks=stacks)
            elif tag in ("-END", "-END*"):
                self.overlay.remove_buff(group_key)

    def _expire_elapsed_stacks(self, current_ms: float):
        """
        Checks if any individual stack timer in self.active_groups has reached its expiration time.
        If 1 stack of a multi-stack buff runs out, reduces stack count by 1 and switches to the
        remaining time of the 2nd stack (closest to running out). If all stacks run out, ends the buff.
        """
        if self.first_event_ms is None or current_ms <= 0:
            return
        cur_s = self.game_sec(current_ms)

        for group_key, grp in list(self.active_groups.items()):
            holder_key, suit_id, effect_key = group_key
            effect_cfg, info = get_effect_config(suit_id, effect_key)
            if effect_cfg.get("no_auto_expire", False):
                continue

            if effect_cfg.get("decay_one", False):
                self._decay_one_stack(group_key, grp, current_ms, cur_s)
                continue

            expiries = grp.get("stack_expiries_s", [])
            if not expiries:
                continue

            expired_last_s = None
            while expiries and cur_s >= expiries[0]:
                expired_last_s = expiries.pop(0)

            if expired_last_s is not None:
                set_name, dur_str = grp["info"]
                effect_label = effect_cfg.get("label", "")
                caster_ptr = grp.get("caster_ptr", "")
                stat_key = (holder_key, suit_id, effect_key, set_name, dur_str)

                if not expiries:
                    # All stacks have expired -> remove buff completely until next start/refresh
                    st = self.buff_stats.setdefault(
                        stat_key, {"procs": 0, "refreshes": 0, "intervals": [], "peak_stacks": 1, "caster_ptr": caster_ptr}
                    )
                    st["intervals"].append((grp["group_start_ms"], current_ms))
                    del self.active_groups[group_key]
                    self.pending_detaches.pop(group_key, None)

                    dur_total = max(0.0, expired_last_s - self.game_sec(grp["group_start_ms"]))
                    self._print_live_event(
                        current_ms, "-END", holder_key, caster_ptr, suit_id, set_name, 0, f"Lasted {dur_total:5.2f}s",
                        effect_key=effect_key, effect_label=effect_label,
                    )
                else:
                    # Reduced by 1 stack; timer switches to the next stack closest to running out!
                    rem_stacks = len(expiries)
                    grp["cur_stacks"] = rem_stacks
                    rem_next_s = max(0.0, expiries[0] - cur_s)
                    self._print_live_event(
                        current_ms, "-STACK", holder_key, caster_ptr, suit_id, set_name, rem_stacks, f"{rem_next_s:5.2f}s left",
                        effect_key=effect_key, effect_label=effect_label,
                    )

    def _decay_one_stack(self, group_key, grp, current_ms: float, cur_s: float):
        """Decay one stack, then refresh the remaining stacks' 25s timer."""
        expiries = grp.get("stack_expiries_s", [])
        if not expiries:
            return

        holder_key, suit_id, effect_key = group_key
        effect_cfg, info = get_effect_config(suit_id, effect_key)
        dur_s = effect_cfg.get("dur_s", 25.0)
        effect_label = effect_cfg.get("label", "")
        last_decay_s = None

        while expiries and cur_s >= expiries[0]:
            decay_at = expiries.pop(0)
            last_decay_s = decay_at
            if expiries:
                # "Duration refreshes when gained or decayed" - refresh the
                # remaining stacks from the moment this stack fell off.
                expiries = [decay_at + dur_s] * len(expiries)

        if last_decay_s is None:
            return

        grp["stack_expiries_s"] = expiries
        set_name, dur_str = grp["info"]
        caster_ptr = grp.get("caster_ptr", "")
        stat_key = (holder_key, suit_id, effect_key, set_name, dur_str)

        if not expiries:
            st = self.buff_stats.setdefault(
                stat_key, {"procs": 0, "refreshes": 0, "intervals": [], "peak_stacks": 1, "caster_ptr": caster_ptr}
            )
            st["intervals"].append((grp["group_start_ms"], current_ms))
            del self.active_groups[group_key]
            self.pending_detaches.pop(group_key, None)
            dur_total = max(0.0, last_decay_s - self.game_sec(grp["group_start_ms"]))
            self._print_live_event(
                current_ms, "-END", holder_key, caster_ptr, suit_id, set_name, 0, f"Lasted {dur_total:5.2f}s",
                effect_key=effect_key, effect_label=effect_label,
            )
            return

        rem_stacks = len(expiries)
        grp["cur_stacks"] = rem_stacks
        rem_next_s = max(0.0, expiries[0] - cur_s)
        self._print_live_event(
            current_ms, "-STACK", holder_key, caster_ptr, suit_id, set_name, rem_stacks, f"{rem_next_s:5.2f}s left",
            effect_key=effect_key, effect_label=effect_label,
        )

    def _flush_expired_detaches(self, current_ms: float, force_all: bool = False):
        self._expire_elapsed_stacks(current_ms)

        for group_key in list(self.pending_detaches.keys()):
            queue_list = self.pending_detaches[group_key]
            remaining = []
            for item in queue_list:
                if force_all or (current_ms - item["detach_ms"]) > 60.0:
                    if group_key not in self.active_groups:
                        continue

                    holder_key, suit_id, effect_key = group_key
                    set_name, dur_str = item["info"]
                    grp = self.active_groups[group_key]
                    effect_cfg, _ = get_effect_config(suit_id, effect_key)
                    effect_label = effect_cfg.get("label", "")
                    caster_ptr = grp.get("caster_ptr", "")
                    stat_key = (holder_key, suit_id, effect_key, set_name, dur_str)

                    # Astral Voice's listener/modifier instances are torn down and
                    # rebuilt while the buff is being refreshed.  Its stack timers
                    # are authoritative, so an old instance detaching must not end
                    # the whole buff early.
                    if effect_cfg.get("refresh_all"):
                        continue

                    if len(grp["instances"]) == 0:
                        st = self.buff_stats.setdefault(
                            stat_key, {"procs": 0, "refreshes": 0, "intervals": [], "peak_stacks": 1, "caster_ptr": caster_ptr}
                        )
                        st["intervals"].append((grp["group_start_ms"], item["detach_ms"]))
                        del self.active_groups[group_key]

                        end_s = self.game_sec(item["detach_ms"])
                        dur_s = max(0.0, end_s - self.game_sec(item["group_start_ms"]))
                        self._print_live_event(
                            item["detach_ms"], "-END", holder_key, caster_ptr, suit_id, set_name, 0, f"Lasted {dur_s:5.2f}s",
                            effect_key=effect_key, effect_label=effect_label,
                        )
                    else:
                        # One instance detached while other stack instances remain
                        expiries = grp.get("stack_expiries_s", [])
                        if len(expiries) > 1:
                            expiries.pop(0)
                            rem_stacks = len(expiries)
                            grp["cur_stacks"] = rem_stacks
                            cur_s = self.game_sec(item["detach_ms"])
                            rem_next_s = max(0.0, expiries[0] - cur_s)
                            self._print_live_event(
                                item["detach_ms"], "-STACK", holder_key, caster_ptr, suit_id, set_name, rem_stacks, f"{rem_next_s:5.2f}s left",
                                effect_key=effect_key, effect_label=effect_label,
                            )
                else:
                    remaining.append(item)
            if remaining:
                self.pending_detaches[group_key] = remaining
            else:
                del self.pending_detaches[group_key]

    def _trigger_or_refresh_group(
        self,
        t_ms: float,
        holder_key: str,
        raw_holder: str,
        caster_ptr: str,
        suit_id: str,
        set_name: str,
        dur_str: str,
        self_ptr: str = "",
        mod_name: str = "",
        attach_instance: bool = False,
        effect_key: str = DEFAULT_EFFECT_KEY,
    ):
        effect_cfg, info = get_effect_config(suit_id, effect_key)
        effect_key = effect_cfg.get("key", DEFAULT_EFFECT_KEY)
        group_key = (holder_key, suit_id, effect_key)
        max_st = effect_cfg.get("max_stacks", 1)
        dur_s = effect_cfg.get("dur_s", 15.0)
        refresh_all = effect_cfg.get("refresh_all", False)
        effect_label = effect_cfg.get("label", "")
        cur_s = self.game_sec(t_ms)

        if info.get("elem") and raw_holder and raw_holder != "TEAM":
            self._record_entity_attr(raw_holder, info["elem"])

        pend_list = self.pending_detaches.get(group_key, [])
        refreshed_any = False
        while pend_list and (t_ms - pend_list[0]["detach_ms"]) <= 60.0:
            pend_list.pop(0)
            refreshed_any = True

        was_active = group_key in self.active_groups
        grp = self.active_groups.setdefault(group_key, {
            "instances": set(),
            "stack_expiries_s": [],
            "cur_stacks": 1,
            "group_start_ms": t_ms,
            "last_step_ms": -1000.0,
            "caster_ptr": caster_ptr or raw_holder,
            "info": (set_name, dur_str),
        })
        if caster_ptr:
            grp["caster_ptr"] = caster_ptr

        if info.get("teamwide"):
            if caster_ptr and caster_ptr != "TEAM":
                self.ex_owner_suits.setdefault(caster_ptr.lower(), set()).add(suit_id)
        else:
            if raw_holder and raw_holder != "TEAM":
                self.holder_suits.setdefault(raw_holder.lower(), set()).add(suit_id)
            if holder_key != "TEAM":
                self.holder_suits.setdefault(holder_key, set()).add(suit_id)

        if attach_instance and self_ptr and mod_name:
            grp["instances"].add((self_ptr, mod_name, raw_holder))

        dt_step = t_ms - grp["last_step_ms"]
        # Debounce same-frame events (e.g. mod+ -> modN -> modA -> slot within 100ms)
        if was_active and dt_step <= 100.0:
            return

        grp["last_step_ms"] = t_ms
        self.last_suit_attach_ms[suit_id] = (t_ms, holder_key)

        # Update the stack expiration queue. Most stacked sets use independent
        # timers; sets marked refresh_all (e.g. Astral Voice) reset every stack
        # to the full duration on each repeated trigger.
        expiries = [e for e in grp["stack_expiries_s"] if e > cur_s]
        if max_st <= 1:
            expiries = [cur_s + dur_s]
        elif refresh_all:
            stack_count = min(max_st, max(1, len(expiries) + 1))
            expiries = [cur_s + dur_s] * stack_count
        else:
            if len(expiries) < max_st:
                expiries.append(cur_s + dur_s)
            else:
                expiries.pop(0)
                expiries.append(cur_s + dur_s)
            expiries.sort()

        grp["stack_expiries_s"] = expiries
        cur_stacks = len(expiries) if max_st > 1 else 1
        grp["cur_stacks"] = cur_stacks

        stat_key = (holder_key, suit_id, effect_key, set_name, dur_str)
        st = self.buff_stats.setdefault(
            stat_key, {"procs": 0, "refreshes": 0, "intervals": [], "peak_stacks": 1, "caster_ptr": grp["caster_ptr"]}
        )
        st["peak_stacks"] = max(st["peak_stacks"], cur_stacks)

        # Display remaining time of the stack closest to running out
        closest_rem_s = max(0.0, expiries[0] - cur_s) if expiries else dur_s
        dur_display = f"{closest_rem_s:.1f}s" if (max_st > 1 and cur_stacks > 1) else dur_str

        if was_active or refreshed_any:
            st["refreshes"] += 1
            self._print_live_event(
                t_ms, "~REFRESH", holder_key, grp["caster_ptr"], suit_id, set_name, cur_stacks, dur_display,
                add_stack=True, effect_key=effect_key, effect_label=effect_label,
            )
        else:
            st["procs"] += 1
            self._print_live_event(
                t_ms, "+START", holder_key, grp["caster_ptr"], suit_id, set_name, cur_stacks, dur_str,
                add_stack=True, effect_key=effect_key, effect_label=effect_label,
            )

    @staticmethod
    def _ability_skill_kinds(ability_str: str):
        """Map an ability string such as Cissia_ExSpecial to skill kinds."""
        low = (ability_str or "").lower()
        kinds = set()
        if "_exspecial" in low:
            kinds.add("ex")
        if "_exqte" in low or "_ultimate" in low:
            kinds.add("ultimate")
        elif "_qte" in low or "_chain" in low:
            kinds.add("chain")
        return kinds

    def _refresh_ex_triggered_sets(self, t_ms: float, holder_key: str, caster_ptr: str, skills):
        """Refresh sets such as Dawn's Bloom when their holder uses EX/Ultimate."""
        if not holder_key or holder_key == "TEAM" or not skills:
            return
        holder_key = holder_key.lower()

        for suit_id in list(self.holder_suits.get(holder_key, ())):
            info = DISC_SET_MAP.get(suit_id, {})
            if not (set(info.get("refresh_skills") or ()) & skills):
                continue
            self._trigger_or_refresh_group(
                t_ms,
                holder_key,
                holder_key,
                caster_ptr,
                suit_id,
                info["name"],
                info["dur"],
                attach_instance=False,
            )

        for suit_id in list(self.ex_owner_suits.get(holder_key, ())):
            info = DISC_SET_MAP.get(suit_id, {})
            if not (set(info.get("refresh_skills") or ()) & skills):
                continue
            self._trigger_or_refresh_group(
                t_ms,
                "TEAM",
                holder_key,
                holder_key,
                suit_id,
                info["name"],
                info["dur"],
                attach_instance=False,
            )

        # A few sets proc from any squad member's EX rather than the holder's.
        if "ex" not in skills:
            return
        for group_key, grp in list(self.active_groups.items()):
            holder, suit_id, effect_key = group_key
            info = DISC_SET_MAP.get(suit_id, {})
            if not info.get("refresh_on_any_ex"):
                continue
            self._trigger_or_refresh_group(
                t_ms,
                holder,
                holder,
                grp.get("caster_ptr", ""),
                suit_id,
                info["name"],
                info["dur"],
                attach_instance=False,
                effect_key=effect_key,
            )

    def _refresh_assist_triggered_sets(self, t_ms: float, raw_holder: str, caster_ptr: str = ""):
        """Defensive/Evasive Assist starts can refresh sets like Bunny in Wonderland."""
        for suit_id in list(self.detected_suits):
            info = DISC_SET_MAP.get(suit_id, {})
            if not info.get("refresh_on_assist"):
                continue
            effect_cfg, _ = get_effect_config(suit_id, DEFAULT_EFFECT_KEY)
            holder_key = "TEAM" if info.get("teamwide") else (raw_holder or caster_ptr)
            if not holder_key:
                continue
            self._trigger_or_refresh_group(
                t_ms,
                holder_key,
                raw_holder or holder_key,
                caster_ptr or raw_holder,
                suit_id,
                info["name"],
                info["dur"],
                attach_instance=False,
                effect_key=effect_cfg.get("key", DEFAULT_EFFECT_KEY),
            )

    def _entity_ptr_for_name(self, name: str):
        if not name:
            return None
        target = name.casefold()
        for ptr, entity_name in self.entity_names.items():
            if entity_name.casefold() == target:
                return ptr
        return None

    def _trigger_astral_for_agent(self, t_ms: float, holder_key: str) -> bool:
        """Quick Assist entries are the authoritative Astral Voice trigger."""
        if "50432800" not in self.detected_suits or not holder_key:
            return False
        info = DISC_SET_MAP["50432800"]
        effect_cfg, _ = get_effect_config("50432800", DEFAULT_EFFECT_KEY)
        self._trigger_or_refresh_group(
            t_ms,
            holder_key,
            holder_key,
            "",
            "50432800",
            info["name"],
            info["dur"],
            attach_instance=False,
            effect_key=effect_cfg.get("key", DEFAULT_EFFECT_KEY),
        )
        return True

    def _handle_quick_assist_event(self, t_ms: float, event_name: str):
        cname = extract_codename_from_str(event_name)
        if not cname:
            return
        holder_key = self._entity_ptr_for_name(cname)
        if holder_key and self._trigger_astral_for_agent(t_ms, holder_key):
            return
        self.pending_astral_qa.append((t_ms, cname))
        if len(self.pending_astral_qa) > 20:
            self.pending_astral_qa = self.pending_astral_qa[-20:]

    def _flush_pending_astral_qa(self):
        if not self.pending_astral_qa:
            return
        remaining = []
        for t_ms, cname in self.pending_astral_qa:
            holder_key = self._entity_ptr_for_name(cname)
            if holder_key and self._trigger_astral_for_agent(t_ms, holder_key):
                continue
            remaining.append((t_ms, cname))
        self.pending_astral_qa = remaining

    def _handle_slot_row(self, t_ms: float, stat_ptr: str, a_col: str, slot_idx_str: str, op_kind_str: str, val_str: str):
        try:
            slot_idx = int(slot_idx_str or 0)
            op_kind = int(op_kind_str or 0)
            val = float(val_str or 0.0)
        except ValueError:
            return

        matched_suit_id = None
        matched_holder = None
        matched_caster = ""
        matched_effect_key = DEFAULT_EFFECT_KEY

        if a_col:
            for token in a_col.split(";"):
                if not token:
                    continue
                if "@" in token:
                    mod_name, inst_ptr = token.split("@", 1)
                    inst_ptr = inst_ptr.lower()
                else:
                    mod_name, inst_ptr = token, ""

                meta = self.instance_meta.get(inst_ptr)
                if meta and meta[1] and not HELPER_MOD_RE.search(mod_name):
                    self.stat_ptr_holder[stat_ptr] = meta[1]

                ability_str = self.instance_ability.get(inst_ptr, "")
                suit_id = extract_suit_id(mod_name, ability_str)
                if suit_id:
                    matched_suit_id = suit_id
                    matched_effect_key = resolve_effect_key(suit_id, mod_name, ability_str)
                    if meta and meta[1] and not HELPER_MOD_RE.search(mod_name):
                        matched_holder = meta[1]
                        matched_caster = meta[2]
                        break
                    elif meta and meta[1] and not matched_holder:
                        matched_holder = meta[1]
                        matched_caster = meta[2]

        slot_key = (stat_ptr, slot_idx)
        if matched_suit_id:
            raw_holder = matched_holder or self.stat_ptr_holder.get(stat_ptr)
            if not raw_holder:
                return
            holder_key = self.resolve_holder_key(matched_suit_id, raw_holder)
            self.slot_owner[slot_key] = (holder_key, raw_holder, matched_caster, matched_suit_id, matched_effect_key)
        else:
            owner = self.slot_owner.get(slot_key)
            if not owner:
                return
            holder_key, raw_holder, matched_caster, matched_suit_id, matched_effect_key = owner

        info = DISC_SET_MAP.get(matched_suit_id)
        has_effects = bool(DISC_EFFECTS.get(matched_suit_id))
        effect_cfg, _ = get_effect_config(matched_suit_id, matched_effect_key)
        if not info or op_kind == 3 or abs(val) < 1e-6:
            return
        if effect_cfg.get("max_stacks", 1) <= 1 and not has_effects and not effect_cfg.get("decay_one"):
            return

        # Ignore passive DoRefresh slot recomputes on off-field teammates when another character just triggered the set
        last_att = self.last_suit_attach_ms.get(matched_suit_id)
        if last_att and (t_ms - last_att[0]) <= 80.0 and last_att[1] != holder_key:
            return

        group_key = (holder_key, matched_suit_id, matched_effect_key)
        if group_key in self.active_groups or effect_cfg.get("decay_one") or has_effects:
            self._trigger_or_refresh_group(
                t_ms,
                holder_key,
                raw_holder,
                matched_caster,
                matched_suit_id,
                info["name"],
                effect_cfg.get("dur", info["dur"]),
                attach_instance=False,
                effect_key=matched_effect_key,
            )

    def poll(self):
        # Expire elapsed stacks even during combat lulls when no new TSV lines arrive
        if self.last_event_ms > 0 and self.last_wall_t is not None and self.ts_held_at is None:
            est_ms = self.last_event_ms + (time.perf_counter() - self.last_wall_t) * 1000.0
            self._expire_elapsed_stacks(est_ms)

        for hdr, parts in self.ts_tail.read_new_lines():
            def g(col):
                idx = hdr.get(col, -1)
                return parts[idx] if 0 <= idx < len(parts) else ""
            if g("source") == "awake":
                continue
            try:
                t = float(g("elapsed_ms"))
                world = float(g("world_s"))
                frame = int(g("frame") or 0)
                scale = float(g("scale") or 1.0)
                pause = int(g("pause") or 0)
            except ValueError:
                continue
            self.last_event_ms = max(self.last_event_ms, t)
            self.last_wall_t = time.perf_counter()
            if self.ts_last and (frame < self.ts_last[0] or world < self.ts_last[1]):
                break
            self.ts_last = (frame, world)
            if pause > 0:
                if self.ts_held_at is None:
                    self.ts_held_at = world - self.ts_removed
                self.ts_steps.append((t, self.ts_held_at, 0.0))
            else:
                if self.ts_held_at is not None:
                    self.ts_removed = world - self.ts_held_at
                    self.ts_held_at = None
                self.ts_steps.append((t, world - self.ts_removed, scale))

            effective_scale = 0.0 if self.ts_held_at is not None else max(0.0, min(1.0, scale))
            if self.overlay_time_scale is None or abs(effective_scale - self.overlay_time_scale) > 0.001:
                self.overlay_time_scale = effective_scale
                if self.overlay is not None:
                    self.overlay.set_time_scale(effective_scale)

        for hdr, parts in self.hits_tail.read_new_lines():
            ent_i = hdr.get("arg2", -1)
            sk_i = hdr.get("skillId", -1)
            if ent_i >= 0 and sk_i >= 0 and max(ent_i, sk_i) < len(parts):
                ent = parts[ent_i].lower()
                sk = parts[sk_i]
                if len(sk) >= 7 and sk[:4] in SKILL_PREFIX_MAP:
                    self._vote_entity(ent, SKILL_PREFIX_MAP[sk[:4]], weight=3)
                elif sk.startswith(("530", "540")):
                    self._vote_entity(ent, "Bangboo", weight=2)

        self._find_result_file()
        if self.res_tail:
            for hdr, parts in self.res_tail.read_new_lines():
                def gr(col):
                    idx = hdr.get(col, -1)
                    return parts[idx] if 0 <= idx < len(parts) else ""
                hex_str = gr("result_hex")
                if len(hex_str) < 0x290 * 2:
                    continue
                try:
                    b = bytes.fromhex(hex_str)
                    t_ms = float(gr("elapsed_ms") or 0)
                except ValueError:
                    continue

                self.last_event_ms = max(self.last_event_ms, t_ms)
                self.last_wall_t = time.perf_counter()
                if self.first_event_ms is None or t_ms < self.first_event_ms:
                    self.first_event_ms = t_ms

                att_ptr = f"0x{struct.unpack_from('<Q', b, 0x68)[0]:x}"
                tgt_ptr = f"0x{struct.unpack_from('<Q', b, 0x20)[0]:x}"
                dmg_f = struct.unpack_from("<f", b, 0x118)[0]
                dmg_final = (
                    struct.unpack_from("<d", b, 0x248)[0]
                    if len(b) >= 0x250
                    else math.ceil(dmg_f - 1e-6)
                )
                crit_val = b[0x19C] if len(b) > 0x19C else 0

                for slot_col in ("a8s20_hex", "a8s28_hex", "a8s18_hex"):
                    s_hex = gr(slot_col)
                    if s_hex:
                        try:
                            s_txt = bytes.fromhex(s_hex).decode("utf-16le", errors="ignore")
                            cname = extract_codename_from_str(s_txt)
                            if cname:
                                self._vote_entity(att_ptr, cname, weight=2)
                                break
                        except ValueError:
                            pass

                if dmg_final > 0:
                    self.hit_records.append({
                        "t_ms": t_ms,
                        "attacker": att_ptr,
                        "target": tgt_ptr,
                        "damage": dmg_final,
                        "crit": crit_val > 0,
                    })

        for hdr, parts in self.state_tail.read_new_lines():
            def gs(col):
                idx = hdr.get(col, -1)
                return parts[idx] if 0 <= idx < len(parts) else ""

            for cell in parts:
                if cell:
                    m_suit = SUIT_ABILITY_RE.search(cell)
                    if m_suit:
                        self.detected_suits.add(m_suit.group(1))

            kind = gs("kind")
            try:
                t_ms = float(gs("elapsed_ms") or 0)
            except ValueError:
                t_ms = self.last_event_ms

            if t_ms > 0:
                self.last_event_ms = max(self.last_event_ms, t_ms)
                self.last_wall_t = time.perf_counter()
                if self.first_event_ms is None:
                    self.first_event_ms = t_ms

            self._flush_expired_detaches(t_ms, force_all=False)

            self_ptr = gs("self").lower()
            a_col = gs("a")
            a_ptr_low = a_col.lower()
            b_ptr = gs("b").lower()
            name = gs("name")

            if kind == "modN":
                ability_str = gs("b") or gs("a")
                if self_ptr and ability_str:
                    self.instance_ability[self_ptr] = ability_str
                    if self_ptr in self.instance_meta:
                        m_name, raw_h, caster_p = self.instance_meta[self_ptr]
                        cname = extract_codename_from_str(ability_str)
                        if cname and caster_p:
                            self._vote_entity(caster_p, cname, weight=2)
                            if raw_h == caster_p:
                                self._vote_entity(raw_h, cname, weight=3)

                        elem = extract_element_from_str(ability_str) or extract_element_from_str(m_name)
                        if elem and caster_p:
                            self._record_entity_attr(caster_p, elem)

                        s_id_any = extract_suit_id(m_name, ability_str)
                        if s_id_any and s_id_any in DISC_SET_MAP and DISC_SET_MAP[s_id_any].get("elem") and caster_p:
                            self._record_entity_attr(caster_p, DISC_SET_MAP[s_id_any]["elem"])

                        disc = classify_disc_buff(m_name, ability_str, include_passive=self.include_passive)
                        if disc and raw_h:
                            s_id, s_name, d_str = disc
                            h_key = self.resolve_holder_key(s_id, raw_h)
                            effect_key = resolve_effect_key(s_id, m_name, ability_str)
                            if (h_key, s_id, effect_key) in self.active_groups:
                                self._trigger_or_refresh_group(
                                    t_ms, h_key, raw_h, caster_p, s_id, s_name, d_str, self_ptr, m_name,
                                    attach_instance=False, effect_key=effect_key,
                                )
                continue

            if kind == "slot":
                self._handle_slot_row(t_ms, self_ptr, a_col, gs("i0"), gs("i1"), gs("f0"))
                continue

            if kind == "timer":
                ability_str = self.instance_ability.get(self_ptr, "")
                m_name, raw_h, caster_p = self.instance_meta.get(self_ptr, (name, a_ptr_low, ""))
                disc = classify_disc_buff(m_name, ability_str, include_passive=self.include_passive)
                if disc and raw_h:
                    s_id, s_name, d_str = disc
                    h_key = self.resolve_holder_key(s_id, raw_h)
                    effect_key = resolve_effect_key(s_id, m_name, ability_str)
                    if (h_key, s_id, effect_key) in self.active_groups:
                        self._trigger_or_refresh_group(
                            t_ms, h_key, raw_h, caster_p, s_id, s_name, d_str, self_ptr, m_name,
                            attach_instance=False, effect_key=effect_key,
                        )
                continue

            if kind == "mod+":
                if b_ptr and name:
                    cname = extract_codename_from_str(name)
                    if cname:
                        self._vote_entity(b_ptr, cname, weight=1)
                        if a_ptr_low == b_ptr:
                            self._vote_entity(a_ptr_low, cname, weight=2)
                    elem = extract_element_from_str(name)
                    if elem:
                        self._record_entity_attr(b_ptr, elem)

                self.instance_meta[self_ptr] = (name, a_ptr_low, b_ptr)

                ability_str = self.instance_ability.get(self_ptr, "")
                disc = classify_disc_buff(name, ability_str, include_passive=self.include_passive)
                if disc and a_ptr_low:
                    suit_id, set_name, dur_str = disc
                    holder_key = self.resolve_holder_key(suit_id, a_ptr_low)
                    effect_key = resolve_effect_key(suit_id, name, ability_str)
                    if (holder_key, suit_id, effect_key) in self.active_groups:
                        self._trigger_or_refresh_group(
                            t_ms, holder_key, a_ptr_low, b_ptr, suit_id, set_name, dur_str, self_ptr, name,
                            attach_instance=False, effect_key=effect_key,
                        )
                continue

            if kind == "modA":
                ability_str = self.instance_ability.get(self_ptr, "")
                s_id_any = extract_suit_id(name, ability_str)
                meta_name, meta_holder, meta_caster = self.instance_meta.get(self_ptr, (name, a_ptr_low, b_ptr))
                raw_holder = a_ptr_low or meta_holder
                caster_ptr = b_ptr or meta_caster

                # EX/Ultimate/Chain re-triggers often re-use an existing
                # modifier (modA only, no new modN), so refresh known
                # skill-triggered sets from the carried ability string.
                skills = self._ability_skill_kinds(ability_str)
                if skills and raw_holder:
                    self._refresh_ex_triggered_sets(t_ms, raw_holder, caster_ptr, skills)

                if name in ASSIST_TRIGGER_MODIFIERS and raw_holder:
                    self._refresh_assist_triggered_sets(t_ms, raw_holder, caster_ptr)

                if s_id_any and s_id_any in DISC_SET_MAP and DISC_SET_MAP[s_id_any].get("elem") and raw_holder:
                    self._record_entity_attr(raw_holder, DISC_SET_MAP[s_id_any]["elem"])

                disc = classify_disc_buff(name, ability_str, include_passive=self.include_passive)
                if not disc or not raw_holder:
                    continue

                suit_id, set_name, dur_str = disc
                holder_key = self.resolve_holder_key(suit_id, raw_holder)
                effect_key = resolve_effect_key(suit_id, name, ability_str)
                self._trigger_or_refresh_group(
                    t_ms, holder_key, raw_holder, caster_ptr, suit_id, set_name, dur_str, self_ptr, name,
                    attach_instance=True, effect_key=effect_key,
                )

            elif kind == "modD":
                found_group = None
                for g_key, grp in self.active_groups.items():
                    matches = [inst for inst in grp["instances"] if inst[0] == self_ptr and inst[1] == name]
                    if matches:
                        found_group = g_key
                        for m in matches:
                            grp["instances"].discard(m)
                        break

                if found_group:
                    self.pending_detaches.setdefault(found_group, []).append({
                        "group_start_ms": self.active_groups[found_group]["group_start_ms"],
                        "detach_ms": t_ms,
                        "info": self.active_groups[found_group]["info"],
                    })

        # Quick Assist switch-ins live in events.tsv, not always in state.tsv.
        # They are the authoritative Astral Voice trigger.
        for hdr, parts in self.events_tail.read_new_lines():
            def ge(col):
                idx = hdr.get(col, -1)
                return parts[idx] if 0 <= idx < len(parts) else ""

            event_name = ge("name")
            if not event_name:
                continue
            low_name = event_name.casefold()
            if not (low_name.endswith("_behitaid") or low_name.endswith("_commonaid")):
                continue
            try:
                t_ms = float(ge("elapsed_ms") or 0.0)
            except ValueError:
                continue
            self._handle_quick_assist_event(t_ms, event_name)

        self._flush_pending_astral_qa()

    def finalize_open_buffs(self):
        end_ms = self.last_event_ms
        if self.hit_records:
            end_ms = max(end_ms, max(h["t_ms"] for h in self.hit_records))

        self._flush_expired_detaches(end_ms + 100.0, force_all=True)

        for group_key, grp in list(self.active_groups.items()):
            holder_key, suit_id, effect_key = group_key
            set_name, dur_str = grp["info"]
            effect_cfg, _ = get_effect_config(suit_id, effect_key)
            effect_label = effect_cfg.get("label", "")
            caster_ptr = grp.get("caster_ptr", "")
            stat_key = (holder_key, suit_id, effect_key, set_name, dur_str)

            st = self.buff_stats.setdefault(
                stat_key, {"procs": 1, "refreshes": 0, "intervals": [], "peak_stacks": 1, "caster_ptr": caster_ptr}
            )
            st["intervals"].append((grp["group_start_ms"], end_ms))

            end_s = self.game_sec(end_ms)
            dur_s = max(0.0, end_s - self.game_sec(grp["group_start_ms"]))
            rem_stacks = grp.get("cur_stacks", 1)
            self._print_live_event(
                end_ms, "-END*", holder_key, caster_ptr, suit_id, set_name, rem_stacks, f"Active until end ({dur_s:5.2f}s)",
                effect_key=effect_key, effect_label=effect_label,
            )

        self.active_groups.clear()
        if self.overlay is not None:
            self.overlay.clear_all()

    def print_conclusion(self):
        self.finalize_open_buffs()

        print(f"\n{'=' * 100}")
        print(f" BATTLE CONCLUDED: {self.battle_dir}")
        print(f"{'=' * 100}")

        if self.hit_records:
            target_counts = {}
            for h in self.hit_records:
                target_counts[h["target"]] = target_counts.get(h["target"], 0) + 1
            main_target = max(target_counts.items(), key=lambda x: x[1])[0]

            team_entities = {
                h["attacker"] for h in self.hit_records
                if h["target"] == main_target and h["attacker"] != main_target
            }
            team_hits = [
                h for h in self.hit_records
                if h["attacker"] in team_entities and h["target"] not in team_entities
            ]
            if not team_hits:
                team_hits = self.hit_records

            t_start_s = self.game_sec(min(h["t_ms"] for h in team_hits))
            t_end_s = self.game_sec(max(h["t_ms"] for h in team_hits))
            duration_s = max(1.0, t_end_s - (0.0 if self.ts_steps else t_start_s))

            by_char = {}
            total_damage = 0.0
            for h in team_hits:
                c_name = self.fmt_entity(h["attacker"])
                entry = by_char.setdefault(c_name, {"damage": 0.0, "hits": 0, "crits": 0})
                entry["damage"] += h["damage"]
                entry["hits"] += 1
                if h["crit"]:
                    entry["crits"] += 1
                total_damage += h["damage"]

            team_dps = total_damage / duration_s

            print(f"  Battle Duration : {duration_s:.2f}s (3-Min Reference: {STANDARD_FIGHT_DURATION_S:.0f}s)")
            print(f"  Total Team DMG  : {int(round(total_damage)):,}")
            print(f"  Team DPS Score  : {team_dps:,.1f} DMG/s")
            print(f"{'-' * 100}")
            print(f"  {'Character':<20} {'Total Damage':>15} {'DPS':>14} {'% Dealt':>12}  {'Share Bar':<22}")
            print(f"  {'-' * 20} {'-' * 15} {'-' * 14} {'-' * 12}  {'-' * 22}")

            sorted_chars = sorted(by_char.items(), key=lambda x: x[1]["damage"], reverse=True)
            for c_name, stats in sorted_chars:
                dmg = stats["damage"]
                dps = dmg / duration_s
                share_pct = (dmg / total_damage * 100.0) if total_damage > 0 else 0.0
                bar_len = int(round(share_pct / 5.0))
                bar = "#" * bar_len + "." * (20 - bar_len)
                print(
                    f"  {c_name:<20} {int(round(dmg)):>15,} {dps:>14,.1f} {share_pct:>11.2f}%  [{bar}]"
                )
        else:
            duration_s = max(
                1.0,
                self.game_sec(self.last_event_ms) - self.game_sec(self.first_event_ms or 0.0),
            )
            print("  No damaging hits were recorded in this battle.")

        if self.buff_stats:
            print(f"\n{'-' * 100}")
            print("  DRIVE DISC BUFF SUMMARY & UPTIME")
            print(f"{'-' * 100}")
            print(
                f"  {'Holder':<16} {'Drive Disc Set':<32} {'Stack':<6} {'Trig':>5} {'Refr':>5} "
                f"{'Uptime':>8} {'% Fight':>9} {'% of 3m':>9}  {'Duration'}"
            )
            print(
                f"  {'-' * 16} {'-' * 26} {'-' * 6} {'-' * 5} {'-' * 5} "
                f"{'-' * 8} {'-' * 9} {'-' * 9}  {'-' * 10}"
            )

            sorted_buffs = sorted(
                self.buff_stats.items(),
                key=lambda x: (0 if x[0][0] == "TEAM" else 1, self.fmt_entity(x[0][0]), -x[1]["procs"]),
            )
            for (holder_key, suit_id, effect_key, set_name, dur_str), st in sorted_buffs:
                holder_name = self.fmt_holder_display(holder_key, st.get("caster_ptr", ""))
                effect_cfg, _ = get_effect_config(suit_id, effect_key)
                display_set = f"{set_name} [{effect_cfg.get('label', '')}]" if effect_cfg.get("label") else set_name
                sec_intervals = [
                    (self.game_sec(s_ms), self.game_sec(e_ms)) for s_ms, e_ms in st["intervals"]
                ]
                up_s = merge_intervals(sec_intervals)
                pct_fight = min(100.0, (up_s / duration_s) * 100.0) if duration_s > 0 else 0.0
                pct_3m = min(100.0, (up_s / STANDARD_FIGHT_DURATION_S) * 100.0)

                stack_col = f"x{st['peak_stacks']}" if st["peak_stacks"] > 1 else ""

                print(
                    f"  {holder_name:<16} {display_set:<32} {stack_col:<6} {st['procs']:>5} {st['refreshes']:>5} "
                    f"{up_s:>7.2f}s {pct_fight:>8.1f}% {pct_3m:>8.1f}%  {dur_str}"
                )
        else:
            print("\n  No active Drive Disc buff triggers were recorded in this battle.")

        print(f"{'=' * 100}\n", flush=True)


def find_active_diagnostic_battle(logs_root: str):
    diag_dir = os.path.join(logs_root, ".diagnostics")
    if not os.path.isdir(diag_dir):
        return None

    active_candidates = []
    now = time.time()
    for launch in os.listdir(diag_dir):
        launch_path = os.path.join(diag_dir, launch)
        if not os.path.isdir(launch_path):
            continue
        for sub in os.listdir(launch_path):
            if not BATTLE_DIR_RE.match(sub):
                continue
            b_dir = os.path.join(launch_path, sub)
            if not os.path.isdir(b_dir):
                continue
            if os.path.isfile(os.path.join(b_dir, "battle.txt")):
                continue
            state_f = os.path.join(b_dir, "state.tsv")
            if os.path.isfile(state_f):
                try:
                    mtime = os.path.getmtime(state_f)
                    if now - mtime < 600:
                        active_candidates.append((mtime, b_dir))
                except OSError:
                    continue

    if not active_candidates:
        return None
    active_candidates.sort(key=lambda x: x[0], reverse=True)
    return active_candidates[0][1]


def find_most_recent_completed_battle(logs_root: str):
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    date_dirs = []
    if os.path.isdir(logs_root):
        date_dirs = sorted(
            [
                d for d in os.listdir(logs_root)
                if DATE_DIR_RE.match(d) and os.path.isdir(os.path.join(logs_root, d))
            ],
            reverse=True,
        )
    if today_str in date_dirs:
        date_dirs.remove(today_str)
        date_dirs.insert(0, today_str)

    for d_str in date_dirs:
        d_path = os.path.join(logs_root, d_str)
        cands = []
        for entry in os.listdir(d_path):
            sub = os.path.join(d_path, entry)
            st = os.path.join(sub, "state.tsv")
            if os.path.isdir(sub) and os.path.isfile(st) and os.path.getsize(st) > 100:
                cands.append((os.path.getmtime(st), sub))
        if cands:
            cands.sort(key=lambda x: x[0], reverse=True)
            return cands[0][1]

    diag_dir = os.path.join(logs_root, ".diagnostics")
    diag_cands = []
    if os.path.isdir(diag_dir):
        for root, _, files in os.walk(diag_dir):
            if "state.tsv" in files:
                st = os.path.join(root, "state.tsv")
                if os.path.getsize(st) > 100:
                    diag_cands.append((os.path.getmtime(st), root))
    if diag_cands:
        diag_cands.sort(key=lambda x: x[0], reverse=True)
        return diag_cands[0][1]
    return None


def run_overlay_demo(overlay: DiscOverlayHUD):
    print("[*] Running Overlay Demo (Astral Voice refreshes all stacks to the full 15s on every trigger)...", flush=True)
    overlay.notify_buff(("TEAM", "50433400"), "50433400", "Moonlight Lullaby (4pc)", "Rina", get_character_color("Rina"), 1, 14.0)
    # Stack 1 on Sigrid at t=0s
    overlay.notify_buff(("sigrid", "50432800"), "50432800", "Astral Voice (4pc)", "Sigrid", get_character_color("Sigrid"), 1, 15.0)
    time.sleep(2.5)
    # Second trigger: 2 stacks, both timers reset to 15s
    overlay.notify_buff(("sigrid", "50432800"), "50432800", "Astral Voice (4pc)", "Sigrid", get_character_color("Sigrid"), 2, 15.0)
    time.sleep(2.5)
    # Third trigger: 3 stacks, all timers reset to 15s
    overlay.notify_buff(("sigrid", "50432800"), "50432800", "Astral Voice (4pc)", "Sigrid", get_character_color("Sigrid"), 3, 15.0)
    time.sleep(10.0)
    overlay.clear_all()
    print("[*] Demo finished.", flush=True)


def main():
    parser = argparse.ArgumentParser(
        description="Live Drive Disc Buff Tracker + Minimalist Disc Overlay (F8) + End-of-Battle DPS & Uptime."
    )
    parser.add_argument(
        "logs_folder",
        nargs="?",
        default=None,
        help=(
            "Path to Combat Logs root or a specific battle folder "
            f"(default: auto-detect; currently: {DEFAULT_LOGS_ROOT or 'not found'})"
        ),
    )
    parser.add_argument(
        "--last",
        action="store_true",
        help="Immediately analyze the most recent completed fight and exit",
    )
    parser.add_argument(
        "--no-overlay",
        action="store_true",
        help="Disable the on-screen graphical popup overlay",
    )
    parser.add_argument(
        "--overlay-pos",
        choices=["top-right", "top-left"],
        default="top-right",
        help="Default screen corner if no saved overlay_config.json exists (default: top-right)",
    )
    parser.add_argument(
        "--icons-dir",
        default=DEFAULT_ICONS_DIR,
        help=f"Folder containing Suit<Name>.png / .webp icons (default: {DEFAULT_ICONS_DIR})",
    )
    parser.add_argument(
        "--obs",
        action="store_true",
        help="Make the overlay a normal app window so OBS Window Capture can pick it up",
    )
    parser.add_argument(
        "--obs-bg",
        default=None,
        metavar="COLOR",
        help="Opaque OBS-mode background colour (e.g. #101014); omit for transparent capture",
    )
    parser.add_argument(
        "--test-overlay",
        action="store_true",
        help="Preview the popup overlay on screen for 15 seconds and exit",
    )
    parser.add_argument(
        "--all-mods",
        action="store_true",
        help="Also show passive 2pc/4pc default and listener modifiers",
    )
    args = parser.parse_args()

    if (args.obs or args.obs_bg) and not args.last and not args.no_overlay:
        print(
            "[*] OBS mode: add a Window Capture source and select "
            "'ZZZ Drive Disc Overlay (OBS)'. If transparency is not captured, "
            "relaunch with --obs --obs-bg #101014.",
            flush=True,
        )

    if args.test_overlay:
        hud = DiscOverlayHUD(icons_dir=args.icons_dir, position=args.overlay_pos,
                             obs_mode=args.obs, obs_bg=args.obs_bg)
        run_overlay_demo(hud)
        return

    logs_folder = args.logs_folder if args.logs_folder is not None else DEFAULT_LOGS_ROOT
    if not logs_folder:
        parser.error(
            "Could not auto-detect the Combat Logs folder. "
            "Pass it explicitly, e.g. overl.py \"C:\\path\\to\\Combat Logs\"."
        )
    target = _expand_path(logs_folder)
    if not os.path.isdir(target):
        parser.error(f"Combat Logs folder not found: {target}")
    if args.logs_folder is None:
        print(f"[*] Auto-detected Combat Logs: {target}")

    if os.path.isfile(os.path.join(target, "state.tsv")) or args.last:
        battle_dir = (
            target
            if os.path.isfile(os.path.join(target, "state.tsv"))
            else find_most_recent_completed_battle(target)
        )
        if not battle_dir:
            raise FileNotFoundError(f"No valid battle folder found in {target}")
        print(f"[*] Analyzing battle folder: {battle_dir}\n")
        print(f"  {'Time':<9} {'Event':<10} {'Holder':<16} | {'Drive Disc Set':<32} | {'Stack':<5} | {'Duration'}")
        print(f"  {'-' * 88}")
        session = BattleSession(
            battle_dir, live_print=True, include_passive=args.all_mods, overlay=None
        )
        session.poll()
        session.print_conclusion()
        return

    overlay = None if args.no_overlay else DiscOverlayHUD(
        icons_dir=args.icons_dir, position=args.overlay_pos,
        obs_mode=args.obs, obs_bg=args.obs_bg,
    )

    print(f"[*] Live Drive Disc Tracker + Minimalist Disc Overlay initialized on: {target}")
    print(f"[*] Disc Icons folder: {args.icons_dir} (Found {len(overlay.file_index) // 2 if overlay else 0} icon files)")
    print("[*] OVERLAY CONTROLS: Press [F8] to unlock -> Drag disc to move, drag corner ◢ (or Right-Drag / Scroll) to resize!")
    print("[*] Waiting for battle to start... (Press Ctrl+C to stop)\n")

    seen_completed = set()

    try:
        while True:
            active_dir = find_active_diagnostic_battle(target)
            if not active_dir or active_dir in seen_completed:
                time.sleep(0.4)
                continue

            print(f"{'=' * 100}")
            print(f" [!] ACTIVE BATTLE DETECTED: {active_dir}")
            print(f"  {'Time':<9} {'Event':<10} {'Holder':<16} | {'Drive Disc Set':<32} | {'Stack':<5} | {'Duration'}")
            print(f"  {'-' * 88}")

            session = BattleSession(
                active_dir, live_print=True, include_passive=args.all_mods, overlay=overlay
            )
            while True:
                session.poll()
                battle_txt = os.path.join(active_dir, "battle.txt")
                if not os.path.isdir(active_dir) or os.path.isfile(battle_txt):
                    time.sleep(0.25)
                    session.poll()
                    break
                time.sleep(0.08)

            session.print_conclusion()
            seen_completed.add(active_dir)
            print("[*] Waiting for next battle... (Press Ctrl+C to stop)\n")

    except KeyboardInterrupt:
        print("\n[*] Live tracker stopped.")


if __name__ == "__main__":
    main()