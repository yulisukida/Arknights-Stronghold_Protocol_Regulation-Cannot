import json
import time
import uuid

from . import paths

DEFAULTS = {
    "name": "新规则",
    "template": "",
    "threshold": 0.85,
    "region": None,          # None = full screen, else [left, top, width, height]
    "click": "left",         # left / right / double / scroll / none
    "scroll": 5,             # wheel notches for the scroll action (foreground)
    "scroll_repeat": 1,      # scroll bursts per trigger
    "swipe_dist": 150,       # background scroll = drag this many px per burst
    "scroll_settle": 0.5,    # seconds to wait after a swipe before re-checking
    "offset": [0, 0],
    "pre_clicks": [],        # [[x, y], ...] clicked (absolute) before the main action
    "pre_delay": 0.6,        # seconds between pre-clicks and before the main click
    "dark_slots": [],        # [[x, y], ...]: click the first slot whose patch is dark
    "dark_offset": [0, 85],  # brightness sampled at slot + this offset
    "dark_thresh": 100.0,    # mean patch brightness below this = unselected
    "dark_clicks": 1,        # times to click the chosen dark slot (1s apart)
    "bright_slots": [],      # [[x, y], ...]: all must sit on a bright line to fire
    "bright_thresh": 150.0,  # brightness of the brightest row in the sampled strip
    "bright_min": 0,         # how many bright_slots must pass (0 = all)
    "once_per_appearance": False,  # rearm only when the template disappears
    "consecutive_restart": 0,      # watchdog: N consecutive matches -> restart game (0=off)
    "match_color": False,          # True = BGR color match (distinguish same-shape diff-color buttons)
    "battle_flow": False,          # True = run MAA-style in-game prep flow (gold/buy/deploy/upgrade/ready)
    "upgrade_template": "",        # if set, read gold and click this (升级) button when rich
    "upgrade_if_gold_gt": 30,      # upgrade only when gold exceeds this
    "upgrade_clicks": 2,           # times to click the upgrade button
    "upgrade_threshold": 0.8,
    "upgrade_region": None,        # search area for the shifting upgrade button
    "gold_region": None,           # gold number box (None = OCR default position)
    "interval": 1.0,
    "cooldown": 2.0,
    "max_clicks": 0,         # 0 = unlimited
    "enabled": True,
}


def new_rule(**kw) -> dict:
    rule = dict(DEFAULTS)
    rule["id"] = uuid.uuid4().hex[:8]
    rule["created"] = time.time()
    rule.update(kw)
    return rule


def _rules_file(emu: bool):
    if emu and not paths.RULES_EMU_FILE.exists() and paths.RULES_FILE.exists():
        import shutil
        shutil.copy2(paths.RULES_FILE, paths.RULES_EMU_FILE)
    return paths.RULES_EMU_FILE if emu else paths.RULES_FILE


def load_rules(emu: bool = False) -> list[dict]:
    f = _rules_file(emu)
    if not f.exists():
        return []
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [dict(DEFAULTS, **r) for r in data
            if isinstance(r, dict) and r.get("id")]


def save_rules(rules: list[dict], emu: bool = False) -> None:
    paths.ensure_dirs()
    _rules_file(emu).write_text(
        json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8"
    )


DEFAULT_SETTINGS = {
    "priority_mode": True,   # one cycle = one screenshot, first matching rule clicks
    "cycle_interval": 10.0,  # seconds between cycles in priority mode
    "use_window": False,     # capture the game window; regions/coords window-relative
    "window_title": "明日方舟",
    "background_mode": False,  # PrintWindow + PostMessage: no focus/mouse stealing
    "bg_click_postmsg": True,  # bg clicks: True=PostMsg-WindowPos (no mouse steal), False=SendInput
    "emu_mode": False,       # capture+input through ADB (Android emulator)
    "adb_addr": "127.0.0.1:7555",
    "adb_exe": "adb",
    "game_exe": "",          # PC client exe for watchdog restart (auto-discovered if empty)
    "daily_restart_hhmm": "04:01",  # scheduled daily restart time ("" disables)
    "stuck_restart_minutes": 20,    # restart after this many minutes with no hit (0=off)
}


def load_settings() -> dict:
    settings = dict(DEFAULT_SETTINGS)
    if paths.SETTINGS_FILE.exists():
        try:
            settings.update(json.loads(paths.SETTINGS_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    return settings


def save_settings(settings: dict) -> None:
    paths.ensure_dirs()
    paths.SETTINGS_FILE.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
