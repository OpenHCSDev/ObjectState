"""
Live context resolution service for configuration framework.

Provides cached resolution of config attributes using live values,
avoiding redundant context building and resolution operations.

This service is completely generic and UI-agnostic:
- No knowledge of ParameterFormManager or any UI components
- No knowledge of steps, orchestrators, or domain concepts
- Only knows about dataclasses, context stacks, and attribute resolution
- Caller is responsible for providing live context data
"""

import logging
from objectstate.field_value import FieldValue
from objectstate.construction_binding import admit_target
from typing import Any

from objectstate.context_manager import config_context
from objectstate.lazy_factory import replace_raw

logger = logging.getLogger(__name__)


class _ResolvedAttr:
    """One answer, held together with the objects it was computed from.

    Holding the objects keeps them alive for as long as the answer is kept, and
    the answer is found again by comparing those objects with ``is``.
    """

    __slots__ = ("config_obj", "context_stack", "value")

    def __init__(self, config_obj: object, context_stack: tuple[object, ...], value: Any):
        self.config_obj = config_obj
        self.context_stack = context_stack
        self.value = value

    def computed_from(self, config_obj: object, context_stack: list) -> bool:
        return (
            self.config_obj is config_obj
            and len(self.context_stack) == len(context_stack)
            and all(kept is given for kept, given in zip(self.context_stack, context_stack))
        )


class LiveContextResolver:
    """
    Pure service for resolving config attributes with live values.

    Keeps resolved values to avoid expensive context stack building + resolution.
    The answers kept are those of one cache token. Each is stored with the config
    object and the context objects it was computed from, so it is returned only
    for those same objects. Answers of an earlier token are dropped when a new
    token arrives.

    Completely generic - works with any dataclasses and any context hierarchy.
    UI layer is responsible for:
    - Collecting live context from form managers
    - Providing the current token
    - Building the context stack
    """

    def __init__(self):
        self._answers_token: int | None = None
        self._answers_by_attr: dict[str, list[_ResolvedAttr]] = {}

    def resolve_config_attr(
        self,
        config_obj: object,
        attr_name: str,
        context_stack: list,
        live_context: dict[type, dict[str, Any]],
        cache_token: int,
    ) -> Any:
        """
        Resolve config attribute through context hierarchy with caching.

        Completely generic - no knowledge of UI, steps, orchestrators, or domain concepts.

        Args:
            config_obj: Config dataclass instance to resolve attribute from
            attr_name: Attribute name to resolve (e.g., 'enabled')
            context_stack: List of context objects to resolve through (e.g., [global_config, pipeline_config, step])
            live_context: Live values from form managers, keyed by type
            cache_token: Current cache token for invalidation

        Returns:
            Resolved attribute value
        """
        if cache_token != self._answers_token:
            self._answers_by_attr = {}
            self._answers_token = cache_token

        answers = self._answers_by_attr.setdefault(attr_name, [])
        for answer in answers:
            if answer.computed_from(config_obj, context_stack):
                return answer.value

        resolved_value = self._resolve_uncached(
            config_obj, attr_name, context_stack, live_context
        )
        answers.append(_ResolvedAttr(config_obj, tuple(context_stack), resolved_value))
        return resolved_value

    def invalidate(self) -> None:
        """Drop every kept answer."""
        self._answers_token = None
        self._answers_by_attr = {}


    def _resolve_uncached(
        self,
        config_obj: object,
        attr_name: str,
        context_stack: list,
        live_context: dict[type, dict[str, Any]]
    ) -> Any:
        """Resolve config attribute through context hierarchy (uncached)."""
        # Merge live values into each context object
        merged_contexts = [
            self._merge_live_values(ctx, live_context.get(type(ctx)))
            for ctx in context_stack
        ]

        # Resolve through nested context stack
        return self._resolve_through_contexts(merged_contexts, config_obj, attr_name)

    def _resolve_through_contexts(self, merged_contexts: list, config_obj: object, attr_name: str) -> Any:
        """Resolve through nested context stack using config_context()."""
        # Build nested context managers
        if not merged_contexts:
            # No context - just get attribute directly
            return getattr(config_obj, attr_name)

        # Nest contexts from outermost to innermost
        def resolve_in_context(contexts_remaining):
            if not contexts_remaining:
                # Innermost level - get the attribute
                return getattr(config_obj, attr_name)

            # Enter context and recurse
            ctx = contexts_remaining[0]
            with config_context(ctx):
                return resolve_in_context(contexts_remaining[1:])

        return resolve_in_context(merged_contexts)

    def _merge_live_values(self, base_obj: object, live_values: dict[str, Any] | None) -> object:
        """Merge stored live values without resolving or changing their meaning.

        Literal null overrides saved data. Only Inherit requests context/MRO
        selection; neither directive is a nested configuration container.
        """
        member = admit_target(base_obj)
        updates = {name: member.declaration.field_types[name].admit(value) for name, value in (live_values or {}).items()}
        return member.overlay_fields(updates).stored
