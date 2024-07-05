from contextlib import contextmanager
from time import perf_counter
from typing import Callable, Iterator


@contextmanager
def catchtime() -> Iterator[Callable[[], float]]:
    t1 = t2 = perf_counter()
    yield lambda: t2 - t1
    t2 = perf_counter()
