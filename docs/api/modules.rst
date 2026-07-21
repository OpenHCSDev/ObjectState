API orientation
===============

Configuration and lazy types
----------------------------

``LazyDataclassFactory``
   Builds lazy dataclass types. Generated types expose ``from_config`` and
   ``to_base_config``.

``auto_create_decorator``
   Builds an application-specific configuration decorator and related lazy
   types.

``config_context`` and ``ensure_global_config_context``
   Install concrete configuration used during resolution.

``set_base_config_type``
   Declares the application's root concrete configuration type.

State and history
-----------------

``ObjectState``
   Mutable working state, saved baseline, resolved projection, callbacks, and
   parameter updates for one scoped object.

``ObjectStateRegistry``
   Registry, hierarchy, token invalidation, atomic updates, snapshots, and
   time-travel history for application states.

``Snapshot``, ``StateSnapshot``, and ``Timeline``
   Typed history records.

Axes and generic annotations
----------------------------

``axes_type``, ``with_axes``, and ``get_axes`` provide generic parametric-axis
metadata. Reified ``List``, ``Dict``, ``Set``, ``Tuple``, and ``Optional``
annotations preserve runtime generic arguments for form and state consumers.

The canonical public import surface is ``objectstate.__all__``. Internal module
paths may change independently of that surface.
