import errno
import msvcrt
from pathlib import Path
from typing import BinaryIO

from backend.app.config import PROJECT_ROOT


class TaskRunnerAlreadyActive(RuntimeError):
    pass


def acquire_task_runner_lock() -> BinaryIO:
    lock_path = PROJECT_ROOT / "runtime" / "locks" / "task-runner.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    handle.seek(0)
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError as error:
        handle.close()
        if error.errno in (errno.EACCES, errno.EAGAIN):
            raise TaskRunnerAlreadyActive("Another API process owns the project task runner.") from None
        raise
    return handle


def release_task_runner_lock(handle: BinaryIO) -> None:
    try:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    finally:
        handle.close()
