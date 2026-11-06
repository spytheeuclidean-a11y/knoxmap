"""Stopping a map that is being made, without losing the area it is of.

Generating, building and compiling a town all take minutes, and until now the
only way out of one was to close the window - which threw away the rectangle
drawn on the map with it, so the area had to be found and drawn again.

The window asks the server to stop (POST /api/stop); the long jobs are handed
a `should_stop` callable and look at it wherever they can be interrupted
without leaving half a file behind - between Overpass tiles, between
buildings, between compile batches. When it says yes they raise Stopped,
which the app turns into an ordinary "stopped" reply rather than an error.

Nothing here touches the drawn area or the settings: a stopped map is simply
one that has not been made yet, and pressing the button again starts it over.
"""
from __future__ import annotations


class Stopped(Exception):
    """Raised inside a long job when the window has asked it to stop."""

    def __init__(self, what: str = "the job"):
        super().__init__(f"Stopped {what}.")
        self.what = what


def check(should_stop, what: str = "the job") -> None:
    """Raise Stopped if the window has asked for it. Cheap enough to call in
    a loop: `should_stop` is a set lookup."""
    if should_stop is not None and should_stop():
        raise Stopped(what)


def gather(pool, pending: dict, should_stop, take, what: str = "the job") -> None:
    """Hand each job of a process `pool` to `take(job, key)` as it finishes,
    looking at `should_stop` at least once a second, then shut the pool.

    On a stop - or anything else going wrong - the workers are ended rather
    than waited for. Waiting meant a Stop pressed while a city was being read,
    or its rows of cells made, did nothing for minutes: each worker finished
    the big piece it was on first. Only what `take` was handed counts as done.
    """
    from concurrent.futures import FIRST_COMPLETED, wait
    try:
        while pending:
            finished, _ = wait(pending, timeout=1.0, return_when=FIRST_COMPLETED)
            for fut in finished:
                take(fut, pending.pop(fut))
            check(should_stop, what)
    except BaseException:
        end = getattr(pool, "terminate_workers", None)      # Python 3.14+
        if end is not None:
            end()
        else:
            pool.shutdown(wait=False, cancel_futures=True)
        raise
    pool.shutdown()
