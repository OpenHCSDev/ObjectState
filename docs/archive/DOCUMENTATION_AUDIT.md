# Superseded documentation audit

This point-in-time audit has been implemented and is no longer an API
authority. It also predated the rename of `ObjectState.save()` to
`ObjectState.mark_saved()`.

Use the current sources instead:

- `README.md` for the public quick start;
- `docs/quickstart.rst` and `docs/state_management.rst` for task guidance;
- `docs/api/modules.rst` for generated API documentation.

Current history navigation uses `ObjectStateRegistry.time_travel_back()` and
`ObjectStateRegistry.time_travel_forward()`. Current baseline management uses
`ObjectState.mark_saved()` and `ObjectState.restore_saved()`.
