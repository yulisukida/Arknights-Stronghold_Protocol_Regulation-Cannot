"""Launch test_admin_click.py elevated (UAC). Runtime paths avoid escape issues."""
import ctypes
import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
name = sys.argv[1] if len(sys.argv) > 1 else "test_admin_click.py"
script = os.path.join(here, name)
ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, f'"{script}"', here, 1)