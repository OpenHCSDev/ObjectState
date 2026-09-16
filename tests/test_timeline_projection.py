"""Timeline persistence derives its field schema from the declaration."""

from dataclasses import dataclass, fields

import pytest

from objectstate.snapshot_model import Timeline


def test_timeline_round_trip_preserves_all_declared_values():
    timeline = Timeline("review", "head", "base", 1789520358.25, "retained")

    payload = timeline.to_dict()

    assert set(payload) == {item.name for item in fields(Timeline)}
    assert Timeline.from_dict(payload) == timeline


@pytest.mark.parametrize("missing", [item.name for item in fields(Timeline)])
def test_timeline_requires_each_declared_field_even_with_a_default(missing):
    payload = Timeline("review", "head", "base").to_dict()
    del payload[missing]

    with pytest.raises(KeyError) as failure:
        Timeline.from_dict(payload)

    assert failure.value.args == (missing,)


def test_timeline_ignores_unknown_document_keys():
    timeline = Timeline("review", "head", "base")
    payload = timeline.to_dict()
    payload["future_extension"] = "not a declared constructor field"

    assert Timeline.from_dict(payload) == timeline


def test_timeline_projection_includes_subclass_declaration_without_a_field_mirror():
    @dataclass
    class ExtendedTimeline(Timeline):
        annotation: str = "declared"

    timeline = ExtendedTimeline("review", "head", "base", annotation="retained")

    assert timeline.to_dict()["annotation"] == "retained"
    assert ExtendedTimeline.from_dict(timeline.to_dict()) == timeline
