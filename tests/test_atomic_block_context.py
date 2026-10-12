"""Block state belongs to the context that opened the block (issue #30)."""

import asyncio
import threading
from dataclasses import dataclass

import pytest

from objectstate import ObjectState
from objectstate.object_state_registry import ObjectStateRegistry


@dataclass
class Dummy:
    x: int = 1


@pytest.fixture(autouse=True)
def empty_registry():
    ObjectStateRegistry.clear()
    yield
    ObjectStateRegistry.clear()


class HeldOpen:
    """Run a body on another thread and hold it inside until released."""

    def __init__(self, body) -> None:
        self._inside = threading.Event()
        self._release = threading.Event()
        self._errors: list[BaseException] = []
        self._thread = threading.Thread(target=self._run, args=(body,))

    def _run(self, body) -> None:
        try:
            with body():
                self._inside.set()
                self._release.wait(timeout=10)
        except BaseException as error:  # reported to the test thread
            self._errors.append(error)
            self._inside.set()

    def __enter__(self) -> "HeldOpen":
        self._thread.start()
        assert self._inside.wait(timeout=10)
        return self

    def __exit__(self, *exc_info) -> None:
        self._release.set()
        self._thread.join(timeout=10)
        assert not self._errors, self._errors


def _block_facts() -> tuple[int, str | None]:
    block = ObjectStateRegistry.current_atomic_block()
    return (0, None) if block is None else (block.depth, block.label)


def test_thread_outside_any_block_does_not_see_another_threads_block() -> None:
    """The reproducer of issue #30."""
    with HeldOpen(lambda: ObjectStateRegistry.atomic("worker edit")):
        assert _block_facts() == (0, None)
        with ObjectStateRegistry.atomic("main edit"):
            assert _block_facts() == (1, "main edit")
        assert _block_facts() == (0, None)


def test_snapshot_is_not_absorbed_into_another_threads_block() -> None:
    state = ObjectState(Dummy(), scope_id="/plate::step_0")
    ObjectStateRegistry.register(state, _skip_snapshot=True)

    with HeldOpen(lambda: ObjectStateRegistry.atomic("worker edit")):
        ObjectStateRegistry.record_snapshot("main snapshot")
        assert [s.label for s in ObjectStateRegistry.get_branch_history()] == ["main snapshot"]

        with ObjectStateRegistry.atomic("main edit", scope_id="/plate::step_0"):
            state.update_parameter("x", 2)
        labels = [s.label for s in ObjectStateRegistry.get_branch_history()]
        assert "main edit [/plate::step_0]" in labels


def test_atomic_success_in_another_thread_is_outermost_for_its_own_context() -> None:
    state = ObjectState(Dummy(), scope_id="/plate::step_0")
    ObjectStateRegistry.register(state, _skip_snapshot=True)

    with HeldOpen(lambda: ObjectStateRegistry.atomic_success("worker edit")):
        with ObjectStateRegistry.atomic_success("main edit", scope_id="/plate::step_0"):
            assert _block_facts() == (1, "main edit")
            state.update_parameter("x", 2)
        labels = [s.label for s in ObjectStateRegistry.get_branch_history()]
        assert "main edit [/plate::step_0]" in labels


def test_nested_blocks_in_one_context_share_the_outer_block() -> None:
    with ObjectStateRegistry.atomic("outer"):
        with ObjectStateRegistry.atomic_success("inner"):
            assert _block_facts() == (2, "outer")
        assert _block_facts() == (1, "outer")
    assert _block_facts() == (0, None)


def test_block_follows_the_same_owner_as_config_context_across_tasks() -> None:
    """A task started inside a block inherits it; a sibling task does not."""

    async def facts() -> tuple[int, str | None]:
        return _block_facts()

    async def scenario() -> tuple[tuple[int, str | None], tuple[int, str | None]]:
        sibling = asyncio.ensure_future(facts())
        with ObjectStateRegistry.atomic("task edit"):
            child = asyncio.ensure_future(facts())
            inherited = await child
        return inherited, await sibling

    inherited, sibling = asyncio.run(scenario())
    assert inherited == (1, "task edit")
    assert sibling == (0, None)


def test_deferral_in_one_thread_does_not_queue_another_threads_invalidation() -> None:
    state = ObjectState(Dummy(), scope_id="/plate::step_0")
    ObjectStateRegistry.register(state, _skip_snapshot=True)

    def invalidate() -> None:
        ObjectStateRegistry.invalidate_by_type_and_scope(
            scope_id="/plate::step_0",
            changed_type=Dummy,
            field_name="x",
        )

    with HeldOpen(ObjectStateRegistry.defer_live_invalidations):
        invalidate()
        assert not ObjectStateRegistry.has_deferred_invalidations()

    with ObjectStateRegistry.defer_live_invalidations():
        invalidate()
        assert ObjectStateRegistry.has_deferred_invalidations()
    ObjectStateRegistry.flush_deferred_invalidations()
    assert not ObjectStateRegistry.has_deferred_invalidations()
