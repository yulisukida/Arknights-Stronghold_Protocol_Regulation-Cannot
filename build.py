"""One-file exe build. Run: python build.py  (or just build.bat).

The Chinese exe name lives here (UTF-8 Python source) instead of in the
batch file, because cmd.exe misreads UTF-8 .bat bytes after a chcp switch.
PyInstaller builds under a safe ASCII name; the output exe is then renamed.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

BUILD_NAME = "ScreenBot"                       # ASCII, safe for PyInstaller
FINAL_NAME = "卫戍协议坎诺特挂机工具_v2.exe"     # what the user sees (v2 upgrade)


def run(cmd: list[str]) -> None:
    print("+", subprocess.list2cmdline(cmd), flush=True)
    rc = subprocess.call(cmd)
    if rc != 0:
        print("Build failed.", flush=True)
        sys.exit(rc)


run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
run([sys.executable, "-m", "pip", "install", "pyinstaller"])
run([sys.executable, "-m", "PyInstaller",
     "--noconfirm", "--onefile", "--windowed", "--uac-admin",
     "--distpath", ".", "--workpath", "build", "--specpath", ".",
     "--icon=assets/icon.ico",
     "--add-data", "config;config",
     "--add-data", "templates;templates",
     "--add-data", "assets;assets",
     "--collect-all", "rapidocr_onnxruntime",
     # heavy environment packages the tool/OCR never use -> keep the exe small
     "--exclude-module", "torch",
     "--exclude-module", "torchvision",
     "--exclude-module", "torchaudio",
     "--exclude-module", "functorch",
     "--exclude-module", "torchgen",
     "--exclude-module", "pandas",
     "--exclude-module", "scipy",
     "--exclude-module", "matplotlib",
     "--name", BUILD_NAME, "main.py"])

src = ROOT / (BUILD_NAME + ".exe")
dst = ROOT / FINAL_NAME
if src.exists():
    try:
        if dst.exists():
            dst.unlink()
        os.replace(src, dst)
    except PermissionError:
        print("\n注意：目标 exe 正在运行被占用，无法改名。", flush=True)
        print("已生成 ScreenBot.exe（含全部功能）。请关闭正在运行的程序后，", flush=True)
        print("手动把 ScreenBot.exe 改名为", FINAL_NAME, "，或重新运行 build。", flush=True)

if (ROOT / "dist").exists():
    shutil.rmtree(ROOT / "dist", ignore_errors=True)

print("\nBuild OK:", FINAL_NAME, "(in this folder)", flush=True)