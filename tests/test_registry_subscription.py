"""Ownership contracts for ObjectState registry callback subscriptions."""

import pytest

from objectstate import ObjectStateRegistry
from objectstate.object_state_registry import ObjectStateRegistrySubscription


@pytest.mark.parametrize(
    ("add", "remove", "callback"),
    (
        (
            ObjectStateRegistry.add_register_callback,
            ObjectStateRegistry.remove_register_callback,
            lambda _scope, _state: None,
        ),
        (
            ObjectStateRegistry.add_unregister_callback,
            ObjectStateRegistry.remove_unregister_callback,
            lambda _scope, _state: None,
        ),
        (
            ObjectStateRegistry.add_time_travel_complete_callback,
            ObjectStateRegistry.remove_time_travel_complete_callback,
            lambda _states, _scope: None,
        ),
        (
            ObjectStateRegistry.add_history_changed_callback,
            ObjectStateRegistry.remove_history_changed_callback,
            lambda: None,
        ),
        (
            ObjectStateRegistry.add_resolved_changed_callback,
            ObjectStateRegistry.remove_resolved_changed_callback,
            lambda _scope, _paths: None,
        ),
        (
            ObjectStateRegistry.connect_listener,
            ObjectStateRegistry.disconnect_listener,
            lambda: None,
        ),
    ),
)
def test_registry_callback_axes_return_one_release_handle(
    add,
    remove,
    callback,
) -> None:
    subscription = add(callback)
    try:
        assert isinstance(subscription, ObjectStateRegistrySubscription)
        assert subscription.release()
        assert not subscription.release()
    finally:
        remove(callback)


def test_history_callback_subscription_releases_exact_registration() -> None:
    observed = []

    def observe() -> None:
        observed.append(True)

    subscription = ObjectStateRegistry.add_history_changed_callback(observe)
    try:
        assert isinstance(subscription, ObjectStateRegistrySubscription)
        ObjectStateRegistry._fire_history_changed_callbacks()
        assert observed == [True]

        assert subscription.release()
        assert not subscription.release()
        ObjectStateRegistry._fire_history_changed_callbacks()
        assert observed == [True]
    finally:
        ObjectStateRegistry.remove_history_changed_callback(observe)


def test_duplicate_registration_does_not_transfer_existing_ownership() -> None:
    def observe() -> None:
        pass

    owner = ObjectStateRegistry.add_history_changed_callback(observe)
    duplicate = ObjectStateRegistry.add_history_changed_callback(observe)
    try:
        assert not duplicate.release()
        ObjectStateRegistry._fire_history_changed_callbacks()
        assert owner.release()
    finally:
        ObjectStateRegistry.remove_history_changed_callback(observe)
