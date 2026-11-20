"""The lab's clock: every pause the lab takes (`latency`, `throttle`'s pacing) waits on it.

Real time in mitmweb. tests/chain.py swaps in a test clock, so a test never really
sleeps, and latency and pacing run on one test timeline.
"""

import asyncio
import time


class RealTime:
    now = staticmethod(time.monotonic)
    sleep = staticmethod(asyncio.sleep)


current = RealTime()


def now():
    return current.now()


async def sleep(seconds):
    await current.sleep(seconds)
