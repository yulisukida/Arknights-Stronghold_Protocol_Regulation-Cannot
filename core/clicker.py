import pyautogui

pyautogui.FAILSAFE = True   # slam the mouse to the top-left corner to abort
pyautogui.PAUSE = 0.0


def click_at(x: int, y: int, kind: str = "left") -> None:
    if kind == "none":
        return
    pyautogui.moveTo(x, y, duration=0)
    pyautogui.sleep(0.03)
    if kind == "right":
        pyautogui.mouseDown(button="right")
        pyautogui.sleep(0.06)
        pyautogui.mouseUp(button="right")
    elif kind == "double":
        pyautogui.click(x, y)
        pyautogui.sleep(0.05)
        pyautogui.click(x, y)
    else:
        pyautogui.mouseDown()
        pyautogui.sleep(0.06)
        pyautogui.mouseUp()


def click_at_restore(x: int, y: int, kind: str = "left") -> None:
    """Click via SendInput but restore the cursor position afterwards.

    For Unity clients that read the mouse through Raw Input (PostMessage is
    ignored). Does not steal focus; the cursor only teleports briefly.
    """
    ox, oy = pyautogui.position()
    try:
        click_at(x, y, kind)
    finally:
        pyautogui.moveTo(ox, oy, duration=0)


def scroll_at_restore(x: int, y: int, amount: int = 5) -> None:
    ox, oy = pyautogui.position()
    try:
        scroll_at(x, y, amount)
    finally:
        pyautogui.moveTo(ox, oy, duration=0)


def scroll_at(x: int, y: int, amount: int = 5) -> None:
    """Move to (x, y) and scroll the wheel down `amount` notches."""
    pyautogui.moveTo(x, y, duration=0)
    pyautogui.scroll(-abs(int(amount)))
