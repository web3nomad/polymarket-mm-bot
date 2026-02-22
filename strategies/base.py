"""Base strategy interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from core.models import Market, PortfolioState, Signal


class BaseStrategy(ABC):
    """All strategies implement this interface."""

    name: str = "base"

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.enabled = bool(config.get("enabled", True))

    @abstractmethod
    def analyze(self, markets: list[Market], portfolio: PortfolioState) -> list[Signal]:
        """Analyze markets and return trading signals."""
        ...
