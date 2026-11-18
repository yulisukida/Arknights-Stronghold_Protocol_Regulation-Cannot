import sys
from pathlib import Path


def base_dir() -> Path:
    # frozen exe: use the exe's folder; dev: use the project root
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = base_dir()
TEMPLATE_DIR = BASE_DIR / "templates"
CONFIG_DIR = BASE_DIR / "config"
ASSET_DIR = BASE_DIR / "assets"
ICON_FILE = ASSET_DIR / "icon.ico"
RULES_FILE = CONFIG_DIR / "rules.json"
RULES_EMU_FILE = CONFIG_DIR / "rules_emu.json"
SETTINGS_FILE = CONFIG_DIR / "settings.json"


def ensure_dirs() -> None:
    TEMPLATE_DIR.mkdir(exist_ok=True)
    CONFIG_DIR.mkdir(exist_ok=True)
    ASSET_DIR.mkdir(exist_ok=True)
    _seed_bundled()


def _seed_bundled() -> None:
    """First run of the packaged exe: unpack the rules/templates that were
    embedded with --add-data next to the exe, so one file is self-contained."""
    if not getattr(sys, "frozen", False):
        return
    import shutil
    root = Path(getattr(sys, "_MEIPASS", "."))
    for name in ("rules.json", "settings.json"):
        dst = CONFIG_DIR / name
        src = root / "config" / name
        if not dst.exists() and src.exists():
            shutil.copy2(src, dst)
    src_tpl = root / "templates"
    if src_tpl.is_dir():
        for f in src_tpl.glob("*.png"):
            dst = TEMPLATE_DIR / f.name
            if not dst.exists():
                shutil.copy2(f, dst)
    src_assets = root / "assets"
    if src_assets.is_dir():
        for f in src_assets.iterdir():
            dst = ASSET_DIR / f.name
            if f.is_file() and not dst.exists():
                shutil.copy2(f, dst)
