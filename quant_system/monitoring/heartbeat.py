from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
import logging

from quant_system.config import HeartbeatConfig


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class HeartbeatMonitor:
    config: HeartbeatConfig
    last_seen: datetime = field(default_factory=lambda: datetime.now(UTC))

    def beat(self) -> None:
        self.last_seen = datetime.now(UTC)

    async def watch(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self.config.interval_seconds)
                break
            except asyncio.TimeoutError:
                pass
            age = (datetime.now(UTC) - self.last_seen).total_seconds()
            if age > self.config.stale_after_seconds:
                LOGGER.warning("Heartbeat stale for %.1f seconds", age)
