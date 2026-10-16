"""Placeholder presentation over the canonical resolver and admitted members."""

from objectstate.field_value import FieldValue


class LazyDefaultPlaceholderService:
    """Format actual resolved data without another inheritance/default algorithm."""

    PLACEHOLDER_PREFIX = "Default"

    @staticmethod
    def get_lazy_resolved_placeholder(
        dataclass_type: type,
        field_name: str,
        placeholder_prefix: str | None = None,
        context_obj=None,
    ) -> str:
        from objectstate.context_manager import config_context
        from objectstate.dual_axis_resolver import resolve_with_provenance

        prefix = (
            LazyDefaultPlaceholderService.PLACEHOLDER_PREFIX
            if placeholder_prefix is None else placeholder_prefix
        )
        from contextlib import nullcontext

        context = config_context(context_obj) if context_obj is not None else nullcontext()
        with context:
            member = FieldValue.of(resolve_with_provenance(dataclass_type, field_name).value)
            return LazyDefaultPlaceholderService.format_placeholder(member, prefix)

    @staticmethod
    def format_placeholder(value, prefix: str) -> str:
        text = FieldValue.of(value).placeholder_text()
        if not prefix:
            return text
        separator = "" if prefix.endswith(": ") else " " if prefix.endswith(":") else ": "
        return f"{prefix}{separator}{text}"
