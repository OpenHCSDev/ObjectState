"""Tests for ObjectState projection from semantic owner types to visible UI paths."""

from dataclasses import dataclass, field

from objectstate import ObjectState, mark_ui_hidden_config


def test_project_ui_visible_field_path_remaps_hidden_base_to_visible_subclass():
    @mark_ui_hidden_config
    @dataclass
    class HiddenDisplayConfig:
        colormap: str = "gray"

    @dataclass
    class VisibleStreamingConfig(HiddenDisplayConfig):
        frame_rate: int = 30

    @dataclass
    class RootConfig:
        streaming: VisibleStreamingConfig = field(default_factory=VisibleStreamingConfig)

    state = ObjectState(RootConfig())

    assert state.find_path_for_type(HiddenDisplayConfig) is None
    assert (
        state.project_ui_visible_field_path(HiddenDisplayConfig, "colormap")
        == "streaming.colormap"
    )


def test_project_ui_visible_field_path_returns_none_for_missing_field():
    @mark_ui_hidden_config
    @dataclass
    class HiddenSourceConfig:
        threshold: int = 1

    @dataclass
    class VisibleSourceConfig(HiddenSourceConfig):
        pass

    @dataclass
    class RootConfig:
        source: VisibleSourceConfig = field(default_factory=VisibleSourceConfig)

    state = ObjectState(RootConfig())

    assert state.project_ui_visible_field_path(HiddenSourceConfig, "missing") is None
