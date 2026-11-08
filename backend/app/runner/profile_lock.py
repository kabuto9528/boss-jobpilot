import errno
import msvcrt
from contextlib import contextmanager
from pathlib import Path

import psutil

from backend.app.config import PROJECT_ROOT


class BrowserBusy(RuntimeError):
    code = "BROWSER_BUSY"


@contextmanager
def browser_lock():
    lock_path = PROJECT_ROOT / "runtime" / "locks" / "browser.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            if error.errno in (errno.EACCES, errno.EAGAIN):
                raise BrowserBusy("Another browser task holds the project lock.") from None
            raise
        # Windows releases the lock when the handle closes. Keep the lock file in place.
        yield


def ensure_profiles_idle(profile_root: Path) -> None:
    chromium_names = {"chrome.exe", "chromium.exe", "chrome-headless-shell.exe", "msedge.exe"}
    for process in psutil.process_iter(["name"]):
        if (process.info["name"] or "").lower() not in chromium_names:
            continue
        try:
            arguments = process.cmdline()
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied:
            raise BrowserBusy("Could not verify that Chromium has released the project profiles.") from None
        for argument in arguments:
            option, separator, value = argument.partition("=")
            if option.lower() != "--user-data-dir" or not separator:
                continue
            directory = Path(value)
            if directory.is_absolute() and directory.resolve().is_relative_to(profile_root):
                raise BrowserBusy("Chromium is still using a project browser profile.")
