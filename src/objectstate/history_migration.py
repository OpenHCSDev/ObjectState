"""Explicit trusted upgrades of complete typed history documents."""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

from objectstate.construction_binding import StateConstructionBinding


class HistoryMigration(ABC):
    """An application-owned proof of historical construction declarations."""

    @abstractmethod
    def migrate(
        self,
        document: dict[str, Any],
        constructions: Mapping[str, StateConstructionBinding],
    ) -> dict[str, Any]:
        """Return version 2 or reject; current bindings alone are not history proof."""
