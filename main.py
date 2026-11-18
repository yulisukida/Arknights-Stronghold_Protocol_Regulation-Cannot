import sys


def main() -> None:
    if sys.platform == "win32":
        from core.capture import set_dpi_awareness
        set_dpi_awareness()

    from core import paths
    paths.ensure_dirs()

    from gui.app import App
    App().mainloop()


if __name__ == "__main__":
    main()
