"""Field resolution is one precedence order over (config class, scope) sites.

A site is a config class holding a value for the field in the layer of one scope.
Three classes (``Leaf`` < ``Middle`` < ``Base``) and three scopes (step, plate,
global) give nine sites; every subset of them is resolved for ``Leaf.value``.

Two requirements hold whatever the loop order of the resolver is:

* a site that is most specific on both axes wins;
* the winner of a set of sites stays the winner, with the same reported source,
  when losing sites are removed. A resolver with this property picks the first
  member of one strict total order.

Which axis is the outer loop only shows on a crossed pair: a value on a less
specific class in a more specific scope against a value on a more specific class in
a less specific scope, with no site most specific on both. The policy is class
first: the more specific class wins such a pair. It is stated in
``docs/context_system.rst`` under "Precedence Order" and checked by
``test_crossed_pair_is_won_by_the_more_specific_class``.
"""

import functools
from dataclasses import dataclass, field
from itertools import combinations, product
from typing import NamedTuple

import pytest

from objectstate import (
    LazyDataclassFactory,
    ObjectState,
    ObjectStateRegistry,
    build_context_stack,
    mark_global_config_type,
    set_base_config_type,
    set_global_config_for_editing,
)
from objectstate.dual_axis_resolver import resolve_with_provenance


@dataclass
class Base:
    value: str | None = None


@dataclass
class Middle(Base):
    pass


@dataclass
class Leaf(Middle):
    pass


@dataclass
class GlobalConfig:
    base_config: Base = field(default_factory=Base)
    middle_config: Middle = field(default_factory=Middle)
    leaf_config: Leaf = field(default_factory=Leaf)


mark_global_config_type(GlobalConfig)
LazyBase = LazyDataclassFactory.make_lazy_simple(Base)
LazyMiddle = LazyDataclassFactory.make_lazy_simple(Middle)
LazyLeaf = LazyDataclassFactory.make_lazy_simple(Leaf)


@dataclass
class Holder:
    """A pipeline or a step: one lazy config of each class."""

    base_config: LazyBase = field(default_factory=LazyBase)
    middle_config: LazyMiddle = field(default_factory=LazyMiddle)
    leaf_config: LazyLeaf = field(default_factory=LazyLeaf)


GLOBAL, PLATE, STEP = "", "plate", "plate::step"
CLASSES = (Leaf, Middle, Base)  # most specific first: the MRO of the type being read
SCOPES = (STEP, PLATE, GLOBAL)  # most specific first: innermost layer first
FIELD_OF = {Base: "base_config", Middle: "middle_config", Leaf: "leaf_config"}
LAZY_OF = {Base: LazyBase, Middle: LazyMiddle, Leaf: LazyLeaf}
READ_PATH = "leaf_config.value"

Site = tuple[type, str]
ALL_SITES: tuple[Site, ...] = tuple(product(CLASSES, SCOPES))
ALL_SITE_SETS = tuple(
    frozenset(chosen)
    for size in range(len(ALL_SITES) + 1)
    for chosen in combinations(ALL_SITES, size)
)
OWN_SITE: Site = (Leaf, STEP)

# Every pair with no site most specific on both axes, less specific class first.
CROSSED_PAIRS = tuple(
    ((CLASSES[upper_class], SCOPES[inner_scope]), (CLASSES[lower_class], SCOPES[outer_scope]))
    for lower_class, upper_class in combinations(range(len(CLASSES)), 2)
    for inner_scope, outer_scope in combinations(range(len(SCOPES)), 2)
)


def _value_at(site: Site) -> str:
    config_class, scope = site
    return f"{config_class.__name__}@{scope or 'global'}"


SITE_OF_VALUE = {_value_at(site): site for site in ALL_SITES}


def _objects(sites: frozenset[Site]) -> tuple[GlobalConfig, Holder, Holder]:
    """The global config, the plate and the step holding exactly ``sites``."""

    def configs(scope: str, make_config) -> dict:
        return {
            FIELD_OF[config_class]: make_config(config_class)(
                value=_value_at((config_class, scope))
            )
            for config_class in CLASSES
            if (config_class, scope) in sites
        }

    return (
        GlobalConfig(**configs(GLOBAL, lambda config_class: config_class)),
        Holder(**configs(PLATE, LAZY_OF.__getitem__)),
        Holder(**configs(STEP, LAZY_OF.__getitem__)),
    )


class Reads(NamedTuple):
    """Every kind of read of ``Leaf.value`` on the step, kept apart."""

    stored: str | None  # what the step's own config holds
    attribute: str | None  # plain attribute access on the step's config
    resolver: tuple  # (value, source scope, source type) from the one resolver
    saved_value: str | None  # ObjectState.resolve_saved_object
    saved_source: tuple | None  # its provenance; absent when the step holds the value


@functools.cache
def _reads(sites: frozenset[Site]) -> Reads:
    saved_global, plate, step = _objects(sites)
    set_base_config_type(GlobalConfig)
    set_global_config_for_editing(GlobalConfig, saved_global)
    ancestors = [(PLATE, plate)]

    with build_context_stack(step, ancestors, STEP, use_live=False):
        stored = object.__getattribute__(step.leaf_config, "value")
        attribute = step.leaf_config.value
        resolver = tuple(resolve_with_provenance(LazyLeaf, "value"))

    resolved_step, provenance = ObjectState.resolve_saved_object(
        step, scope_id=STEP, ancestor_objects_with_scopes=ancestors
    )
    return Reads(
        stored, attribute, resolver, resolved_step.leaf_config.value, provenance.get(READ_PATH)
    )


def _winner(sites: frozenset[Site]) -> Site | None:
    """The site the resolver reports as the source, or ``None`` when no site wins."""
    value, source_scope, source_type = _reads(sites).resolver
    if value is None:
        return None
    assert SITE_OF_VALUE[value] == (source_type, source_scope)
    return source_type, source_scope


def test_every_read_kind_agrees_with_the_one_resolver_for_every_set_of_sites():
    for sites in ALL_SITE_SETS:
        reads = _reads(sites)
        winner = _winner(sites)
        expected_value = _value_at(winner) if winner else None

        assert (winner is None) == (not sites), sites
        assert winner is None or winner in sites, sites
        assert reads.attribute == reads.saved_value == expected_value, sites
        if OWN_SITE in sites:
            # The step holds the value itself: nothing is inherited, so no source.
            assert reads.stored == _value_at(OWN_SITE), sites
            assert reads.saved_source is None, sites
        else:
            assert reads.stored is None, sites
            assert reads.saved_source == reads.resolver[1:], sites


def test_site_most_specific_on_both_axes_wins():
    """Both loop orders pick this site, so this is no policy choice."""
    checked = 0
    for sites in ALL_SITE_SETS:
        if not sites:
            continue
        joint_minimum = (
            min((config_class for config_class, _ in sites), key=CLASSES.index),
            min((scope for _, scope in sites), key=SCOPES.index),
        )
        if joint_minimum in sites:
            checked += 1
            assert _winner(sites) == joint_minimum, sites
    assert checked > len(ALL_SITES)


def test_removing_losing_sites_changes_neither_the_winner_nor_its_source():
    """The winner does not depend on which rejected candidates are present."""
    for sites in ALL_SITE_SETS:
        if not sites:
            continue
        reads = _reads(sites)
        winner = _winner(sites)
        losers = sorted(sites - {winner}, key=ALL_SITES.index)
        for kept_count in range(len(losers)):
            for kept in combinations(losers, kept_count):
                fewer = _reads(frozenset(kept) | {winner})
                assert fewer.resolver == reads.resolver, (sites, kept)
                assert fewer.attribute == reads.attribute, (sites, kept)
                assert fewer.saved_value == reads.saved_value, (sites, kept)
                assert fewer.saved_source == reads.saved_source, (sites, kept)


def test_winner_is_the_first_site_of_one_strict_total_order():
    """The order read off the two-site sets alone predicts the winner of every set."""
    beaten_by = {
        site: {
            other
            for other in ALL_SITES
            if other != site and _winner(frozenset({site, other})) == site
        }
        for site in ALL_SITES
    }
    # Total and antisymmetric: of two sites exactly one beats the other.
    for first, second in combinations(ALL_SITES, 2):
        assert (second in beaten_by[first]) != (first in beaten_by[second])
    # Transitive, hence a strict total order: the sites beat 8, 7, ..., 0 others.
    order = sorted(ALL_SITES, key=lambda site: len(beaten_by[site]), reverse=True)
    assert [len(beaten_by[site]) for site in order] == list(reversed(range(len(ALL_SITES))))

    for sites in ALL_SITE_SETS:
        if sites:
            assert _winner(sites) == min(sites, key=order.index), sites


@pytest.mark.parametrize(
    ("inner_scope_site", "specific_class_site"),
    CROSSED_PAIRS,
    ids=[f"{_value_at(a)} vs {_value_at(b)}" for a, b in CROSSED_PAIRS],
)
def test_crossed_pair_is_won_by_the_more_specific_class(inner_scope_site, specific_class_site):
    """The policy: class first.

    The MRO is the outer loop and the layers the inner one, so a value on ``Leaf``
    in the global config beats a value on ``Base`` set on the plate.
    """
    assert inner_scope_site[0] is not specific_class_site[0]
    assert inner_scope_site[1] != specific_class_site[1]
    sites = frozenset({inner_scope_site, specific_class_site})
    reads = _reads(sites)

    assert _winner(sites) == specific_class_site
    assert reads.attribute == reads.saved_value == _value_at(specific_class_site)
    # Each site wins when it stands alone, so the pair is a real contest.
    assert _winner(frozenset({inner_scope_site})) == inner_scope_site
    assert _winner(frozenset({specific_class_site})) == specific_class_site


def test_all_sites_are_ordered_class_first_then_scope():
    """The one order is the product order with the class outer."""
    for sites in ALL_SITE_SETS:
        if sites:
            assert _winner(sites) == min(sites, key=ALL_SITES.index), sites


def test_read_kinds_of_an_editing_state_stay_distinct_and_agree_on_a_crossed_pair():
    """Stored value, resolved value and source of a registered ``ObjectState``.

    The stored value stays ``None``; the resolved value and the source are the
    resolver's answer for the same crossed pair. Which site that is, is the
    class-first order (see the crossed-pair test above).
    """
    crossed = frozenset({(Base, PLATE), (Leaf, GLOBAL)})
    plate_only = frozenset({(Base, PLATE)})

    def editing_state_reads(sites: frozenset[Site]) -> tuple:
        saved_global, plate, step = _objects(sites)
        set_base_config_type(GlobalConfig)
        set_global_config_for_editing(GlobalConfig, saved_global)
        states = []
        try:
            # An ancestor is registered before the state below it is built.
            for scope_id, edited in ((PLATE, plate), (STEP, step)):
                states.append(ObjectState(edited, scope_id=scope_id))
                ObjectStateRegistry.register(states[-1], _skip_snapshot=True)
            step_state = states[-1]
            return (
                step_state.parameters[READ_PATH],
                step_state.get_resolved_value(READ_PATH),
                step_state.get_saved_resolved_value(READ_PATH),
                step_state.get_provenance(READ_PATH),
                object.__getattribute__(step_state.to_object().leaf_config, "value"),
            )
        finally:
            for state in reversed(states):
                ObjectStateRegistry.unregister(state, _skip_snapshot=True)

    for sites in (crossed, plate_only):
        stored, live_value, saved_value, source, rebuilt_stored = editing_state_reads(sites)
        resolver_value, *resolver_source = _reads(sites).resolver

        assert stored is None
        assert rebuilt_stored is None  # resolving does not write the value back
        assert live_value == saved_value == resolver_value
        assert source == tuple(resolver_source)

    # The plate's value reaches the step when it stands alone; the global Leaf value
    # displaces it in the crossed pair.
    assert _winner(plate_only) == (Base, PLATE)
    assert _winner(crossed) == (Leaf, GLOBAL)
