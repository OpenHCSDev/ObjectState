"""Low-noise time-travel phase profiling."""

from __future__ import annotations

from contextlib import contextmanager
import logging
import os
import time
from typing import Iterator


class TimeTravelProfiler:
    """Environment-gated profiler for ObjectState-driven UI restore phases."""

    env_var = "OBJECTSTATE_TIME_TRAVEL_PROFILE"
    logger_name = "objectstate.time_travel_profile"

    @classmethod
    def enabled(cls) -> bool:
        value = os.environ.get(cls.env_var, "")
        return value.lower() in {"1", "true", "yes", "on"}

    @classmethod
    @contextmanager
    def phase(cls, name: str, **facts: object) -> Iterator[None]:
        if not cls.enabled():
            yield
            return

        started = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            fact_text = " ".join(f"{key}={value!r}" for key, value in facts.items())
            logging.getLogger(cls.logger_name).info(
                "TT_PHASE name=%s elapsed_ms=%.3f%s%s",
                name,
                elapsed_ms,
                " " if fact_text else "",
                fact_text,
            )
