"""``LiveContextResolver`` keeps each answer with the objects it was computed from.

No key is built from ``id(...)``: an address is reused once its object is collected,
so an answer keyed by address can be handed to a different object.
"""

import inspect
from dataclasses import dataclass

from objectstate import LiveContextResolver, live_context_resolver


@dataclass
class Settings:
    name: str | None = None


def _counting(resolver: LiveContextResolver) -> list[tuple[object, str]]:
    calls: list[tuple[object, str]] = []
    resolve = resolver._resolve_uncached

    def counted(config_obj, attr_name, context_stack, live_context):
        calls.append((config_obj, attr_name))
        return resolve(config_obj, attr_name, context_stack, live_context)

    resolver._resolve_uncached = counted
    return calls


def test_answer_is_reused_for_the_same_objects_and_token():
    resolver = LiveContextResolver()
    calls = _counting(resolver)
    settings = Settings("a")

    first = resolver.resolve_config_attr(settings, "name", [], {}, cache_token=1)
    second = resolver.resolve_config_attr(settings, "name", [], {}, cache_token=1)

    assert (first, second) == ("a", "a")
    assert len(calls) == 1


def test_equal_but_distinct_object_gets_its_own_answer():
    resolver = LiveContextResolver()
    calls = _counting(resolver)
    one, other = Settings("a"), Settings("a")
    assert one == other

    resolver.resolve_config_attr(one, "name", [], {}, cache_token=1)
    resolver.resolve_config_attr(other, "name", [], {}, cache_token=1)

    assert [obj for obj, _ in calls] == [one, other]
    assert calls[0][0] is one and calls[1][0] is other


def test_object_at_a_reused_address_does_not_get_the_collected_objects_answer():
    """The failure an ``id``-keyed cache has: a new object at an old address."""
    resolver = LiveContextResolver()
    settings = Settings("first")
    assert resolver.resolve_config_attr(settings, "name", [], {}, cache_token=1) == "first"
    del settings

    for attempt in range(200):
        replacement = Settings(f"replacement {attempt}")
        resolved = resolver.resolve_config_attr(replacement, "name", [], {}, cache_token=1)
        assert resolved == f"replacement {attempt}"
        del replacement


def test_different_context_objects_get_their_own_answer():
    resolver = LiveContextResolver()
    calls = _counting(resolver)
    settings = Settings("a")
    context_a, context_b = Settings("x"), Settings("x")

    resolver.resolve_config_attr(settings, "name", [context_a], {}, cache_token=1)
    resolver.resolve_config_attr(settings, "name", [context_a], {}, cache_token=1)
    resolver.resolve_config_attr(settings, "name", [context_b], {}, cache_token=1)
    resolver.resolve_config_attr(settings, "name", [context_a, context_b], {}, cache_token=1)

    assert len(calls) == 3


def test_new_token_drops_the_answers_of_the_old_one():
    resolver = LiveContextResolver()
    settings = Settings("before")
    assert resolver.resolve_config_attr(settings, "name", [], {}, cache_token=1) == "before"

    settings.name = "after"
    assert resolver.resolve_config_attr(settings, "name", [], {}, cache_token=1) == "before"
    assert resolver.resolve_config_attr(settings, "name", [], {}, cache_token=2) == "after"
    assert sum(len(answers) for answers in resolver._answers_by_attr.values()) == 1


def test_invalidate_drops_every_answer():
    resolver = LiveContextResolver()
    settings = Settings("before")
    resolver.resolve_config_attr(settings, "name", [], {}, cache_token=1)

    settings.name = "after"
    resolver.invalidate()

    assert resolver.resolve_config_attr(settings, "name", [], {}, cache_token=1) == "after"


def test_no_key_is_built_from_an_address():
    assert "id(" not in inspect.getsource(live_context_resolver)
