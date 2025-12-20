import time
from typing import Callable, TypeVar

T = TypeVar("T")

def retry(fn: Callable[[], T], tries: int = 6, sleep_sec: float = 6.0, name: str = "task") -> T:
    last_err = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            last_err = e
            if i < tries - 1:
                time.sleep(sleep_sec)
    raise RuntimeError(f"{name} failed after {tries} tries: {last_err}") from last_err
