Atomic operations
=================

``ObjectStateRegistry.atomic`` groups related state mutations into one history
snapshot. Structural registration alone is not a user-edit boundary: registering
or unregistering an ``ObjectState`` does not independently create a snapshot.
The atomic block records only when its body requests or causes a material state
change.

Basic use
---------

Create and register states before editing them, then perform the logical change
inside an atomic block:

.. code-block:: python

   from dataclasses import dataclass

   from objectstate import ObjectState, ObjectStateRegistry

   @dataclass
   class Settings:
       threshold: float = 0.5
       enabled: bool = True

   state = ObjectState(Settings(), scope_id="settings")
   ObjectStateRegistry.register(state)

   with ObjectStateRegistry.atomic("update settings", scope_id="settings"):
       state.update_parameter("threshold", 0.8)
       state.update_parameter("enabled", False)

The optional ``scope_id`` identifies the semantic owner of the mutation. When it
is omitted, the first scoped snapshot request inside the outermost block becomes
the owner.

Nesting
-------

Nested atomic blocks coalesce into the outermost block. The outer label and
scope remain authoritative:

.. code-block:: python

   with ObjectStateRegistry.atomic("configure import", scope_id="settings"):
       state.update_parameter("enabled", True)
       with ObjectStateRegistry.atomic("inner detail"):
           state.update_parameter("threshold", 0.65)

Use ``atomic_success`` when an operation must produce no history entry if its
body raises:

.. code-block:: python

   with ObjectStateRegistry.atomic_success("validated update", scope_id="settings"):
       state.update_parameter("threshold", 0.7)
       validate_settings(state.to_object())

If ``validate_settings`` raises, the success-only block restores its history
bookkeeping and does not record a partial operation snapshot. Application code
is still responsible for rolling back external side effects.

Guidelines
----------

- Use one descriptive label for one user-visible operation.
- Keep I/O and network activity outside the atomic block when possible.
- Pass the owning scope when it is already known.
- Never manipulate the registry's atomic depth or snapshot fields directly.
- Serialize mutations onto one application thread; the registry is process-wide
  state, not a per-thread transaction manager.

See :doc:`../undo_redo` for history navigation and serialization.
