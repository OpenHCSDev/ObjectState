"""Resolved-value notifications exclude storage and save-baseline-only changes."""

from dataclasses import dataclass

import pytest

from objectstate import LazyDataclassFactory, ObjectState, ObjectStateRegistry


@dataclass
class NotificationValues:
    number: int = 3
    maybe: int | None = None


LazyNotificationValues = LazyDataclassFactory.make_lazy_simple(NotificationValues)


@pytest.fixture(autouse=True)
def registry():
    ObjectStateRegistry.clear()
    yield
    ObjectStateRegistry.clear()


def test_same_resolved_default_changes_storage_without_value_notification():
    state = ObjectState(LazyNotificationValues())
    assert state.get_resolved_value("number") == 3
    values = []
    chrome = []
    state.on_resolved_changed(lambda paths: values.append(set(paths)))
    state.on_state_changed(lambda paths: chrome.append(state.is_raw_dirty))
    assert state.update_parameter("number", 3) == set()
    assert state.parameters["number"] == 3
    state.reset_parameter("number")
    assert state.parameters["number"] is None
    assert state.get_resolved_value("number") == 3
    assert values == []
    assert chrome == [True, False]


@pytest.mark.parametrize("warm", (False, True))
def test_real_value_change_has_one_notification_even_without_prior_cache_read(warm):
    state = ObjectState(NotificationValues())
    if warm:
        assert state.get_resolved_value("number") == 3
    values = []
    state.on_resolved_changed(lambda paths: values.append(set(paths)))
    assert state.update_parameter("number", 8) == {"number"}
    assert values == [{"number"}]
    assert state.get_resolved_value("number") == 8


def test_mark_saved_updates_dirty_chrome_without_value_notification():
    state = ObjectState(NotificationValues())
    state.update_parameter("number", 8)
    assert state.dirty_fields == {"number"}
    values = []
    chrome = []
    state.on_resolved_changed(lambda paths: values.append(set(paths)))
    state.on_state_changed(lambda paths: chrome.append(set(paths)))
    state.mark_saved()
    assert state.dirty_fields == set()
    assert state.get_resolved_value("number") == 8
    assert values == []
    assert chrome == [{"number"}]
