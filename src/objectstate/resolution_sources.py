"""The objects a state's resolved values are computed from.

A resolved value of a state is a function of three things: which states are
registered above it, what each of them holds for the field's config type and
field, and what the global config holds. ``ResolutionSources`` is that input as
one value: the global config and the ancestors' objects, in the order the context
layers are entered. A resolved snapshot keeps the sources it was computed from;
it is current exactly while the state would be given the same objects today.

When the objects are not the same, ``fields_that_differ`` names the
``(config type, field name)`` pairs whose stored value is another one, read the
way field resolution reads a layer (``extract_all_configs``). Only fields that
can inherit one of those pairs need to be resolved again.

Objects are compared by identity. ``ObjectState.to_object`` builds a new object
whenever a parameter changed, and ``set_global_config`` stores another
instance, so another identity is the signal that values may differ. Every state
below an edited ancestor asks about the same pair of objects, so the answer for
a pair is kept and computed once per edit.
"""

from collections import OrderedDict
from dataclasses import fields, is_dataclass
from typing import Any, NamedTuple

from objectstate.field_access import DataclassFieldAccess
from objectstate.field_value import Unset

FieldKey = tuple[type, str]

# How many (old object, new object) answers are kept. Each entry holds both
# objects, so their ids cannot be given to other objects while it is kept.
_KEPT_PAIRS = 64
_differing_fields_of_pair: "OrderedDict[tuple[int, int], tuple[Any, Any, frozenset[FieldKey]]]" = (
    OrderedDict()
)


class ResolutionSources(NamedTuple):
    """What one resolved snapshot of a state is computed from.

    ``global_config`` is the global config (``objectstate.global_config``), ``None``
    when there is none (the declared defaults are used then). ``ancestors`` are the
    ``(scope id, object)`` pairs of the states registered above the state, least
    specific first, without global config objects: the global config stands for
    them.
    """

    global_config: Any | None
    ancestors: tuple[tuple[str, Any], ...]

    def same_objects_as(self, other: "ResolutionSources | None") -> bool:
        """Whether ``other`` holds the same objects at the same scopes."""
        if other is None:
            return False
        if self.global_config is not other.global_config:
            return False
        if len(self.ancestors) != len(other.ancestors):
            return False
        for mine, theirs in zip(self.ancestors, other.ancestors):  # on every resolved read
            if mine[1] is not theirs[1] or mine[0] != theirs[0]:
                return False
        return True

    def fields_that_differ(self, earlier: "ResolutionSources | None") -> frozenset[FieldKey] | None:
        """The fields whose stored value differs between ``earlier`` and these sources.

        ``None`` means every field may differ: there is no ``earlier``, other scopes
        have a registered state, or a global config was set where none was (or the
        reverse).
        """
        if earlier is None:
            return None
        if (earlier.global_config is None) != (self.global_config is None):
            return None
        if tuple(scope for scope, _ in earlier.ancestors) != tuple(
            scope for scope, _ in self.ancestors
        ):
            return None
        differing: frozenset[FieldKey] = frozenset()
        if self.global_config is not earlier.global_config:
            differing |= _fields_that_differ(earlier.global_config, self.global_config)
        for (_, before), (_, now) in zip(earlier.ancestors, self.ancestors):
            if before is not now:
                differing |= _fields_that_differ(before, now)
        return differing


def _fields_that_differ(before: Any, now: Any) -> frozenset[FieldKey]:
    """``(config type, field name)`` pairs stored differently in two layer objects."""
    pair = (id(before), id(now))
    kept = _differing_fields_of_pair.get(pair)
    if kept is not None and kept[0] is before and kept[1] is now:
        return kept[2]
    differing = frozenset(_compare_layer_objects(before, now))
    _differing_fields_of_pair[pair] = (before, now, differing)
    while len(_differing_fields_of_pair) > _KEPT_PAIRS:
        _differing_fields_of_pair.popitem(last=False)
    return differing


def _compare_layer_objects(before: Any, now: Any) -> set[FieldKey]:
    from objectstate.context_manager import extract_all_configs

    configs_before = extract_all_configs(before)
    configs_now = extract_all_configs(now)
    held_before = {id(config) for config in configs_before.values()}
    held_now = {id(config) for config in configs_now.values()}
    differing: set[FieldKey] = set()
    for config_type in configs_before.keys() | configs_now.keys():
        config_before = configs_before.get(config_type)
        config_now = configs_now.get(config_type)
        if config_before is config_now:
            continue
        names = {
            f.name for config in (config_before, config_now) if config is not None
            for f in fields(config)
        }
        if config_before is None or config_now is None:
            # A layer that starts or stops holding a config type changes where an
            # unset field is reported to live, whatever the values are.
            differing.update((config_type, name) for name in names)
            continue
        for name in names:
            value_before = _stored(config_before, name)
            value_now = _stored(config_now, name)
            if id(value_before) in held_before and id(value_now) in held_now:
                continue  # a nested config on both sides: compared under its own type
            if not _same_stored_value(value_before, value_now):
                differing.add((config_type, name))
    return differing


def _stored(config: Any, name: str) -> Any:
    """The raw field of a config, without lazy resolution; ``None`` when absent."""
    if config is None:
        return Unset()
    try:
        return DataclassFieldAccess.raw_value(config, name)
    except AttributeError:
        return Unset()


def _same_stored_value(a: Any, b: Any) -> bool:
    """Equality of two stored values that never resolves a lazy field.

    Dataclass instances are compared field by field on their stored values: their
    own ``__eq__`` reads attributes, which resolves lazy fields in the caller's
    context. A value whose comparison fails or is not a plain truth value counts
    as different.
    """
    if a is b:
        return True
    if type(a) is not type(b):
        return False
    if is_dataclass(a) and not isinstance(a, type):
        return all(_same_stored_value(_stored(a, f.name), _stored(b, f.name)) for f in fields(a))
    try:
        return bool(a == b)
    except Exception:
        return False
