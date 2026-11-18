from pynput import keyboard


class Hotkeys:
    """Global F8 = toggle start/pause, F9 = stop."""

    def __init__(self, on_toggle, on_stop):
        self._listener = keyboard.GlobalHotKeys({
            "<f8>": on_toggle,
            "<f9>": on_stop,
        })

    def start(self) -> None:
        self._listener.start()

    def stop(self) -> None:
        self._listener.stop()
