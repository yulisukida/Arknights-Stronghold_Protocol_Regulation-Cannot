"""Generate config/rules_emu.json from config/rules.json for an emulator set
to 1280x689 (PC window content area without the 31px title bar).

All absolute y coordinates shift by -Y_SHIFT. Relative values (offset,
dark_offset) stay untouched. Run:  python make_emu_rules.py [Y_SHIFT]
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "config" / "rules.json"
DST = ROOT / "config" / "rules_emu.json"


def shift_y(y: int) -> int:
    return y - Y_SHIFT


def convert(rule: dict) -> dict:
    r = dict(rule)
    if r.get("region"):
        reg = list(r["region"])
        reg[1] = shift_y(int(reg[1]))
        r["region"] = reg
    for key in ("pre_clicks", "dark_slots", "bright_slots"):
        if r.get(key):
            r[key] = [[int(p[0]), shift_y(int(p[1]))] for p in r[key]]
    return r


if __name__ == "__main__":
    Y_SHIFT = int(sys.argv[1]) if len(sys.argv) > 1 else 31
    rules = json.loads(SRC.read_text(encoding="utf-8"))
    out = [convert(r) for r in rules]
    DST.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"已生成 {DST}（y 坐标平移 -{Y_SHIFT}）")
