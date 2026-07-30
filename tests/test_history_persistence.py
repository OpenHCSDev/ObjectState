"""Typed ObjectState history document persistence."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from objectstate import ObjectState, ObjectStateRegistry


class HistoryMode(Enum):
    """Representative nominal configuration value."""

    FAST = "fast"


def identity(value):
    """Representative importable callable configuration value."""

    return value


@dataclass
class HistoryConfig:
    output_path: Path
    mode: HistoryMode
    transform: Callable


def _reset_registry_history() -> None:
    ObjectStateRegistry._snapshots.clear()
    ObjectStateRegistry._timelines.clear()
    ObjectStateRegistry._current_timeline = "main"
    ObjectStateRegistry._current_head = None


def test_history_file_round_trips_typed_values(tmp_path: Path) -> None:
    state = ObjectState(
        HistoryConfig(
            output_path=tmp_path / "results",
            mode=HistoryMode.FAST,
            transform=identity,
        ),
        scope_id="typed_history",
    )
    ObjectStateRegistry.register(state, _skip_snapshot=True)
    ObjectStateRegistry.record_snapshot("typed values", scope_id=state.scope_id)
    history_path = tmp_path / "history.objectstate"

    ObjectStateRegistry.save_history_to_file(str(history_path))
    _reset_registry_history()
    ObjectStateRegistry.load_history_from_file(str(history_path))

    snapshot = ObjectStateRegistry.get_branch_history()[-1]
    parameters = snapshot.all_states[state.scope_id].parameters
    assert parameters["output_path"] == tmp_path / "results"
    assert type(parameters["output_path"]) is type(tmp_path)
    assert parameters["mode"] is HistoryMode.FAST
    assert parameters["transform"] is identity
    assert history_path.stat().st_size > 0
