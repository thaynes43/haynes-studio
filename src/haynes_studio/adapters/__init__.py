"""Legacy service adapters (story 425): clients for the in-cluster services the PoC
used, behind an injected command runner, plus the Winter Menu private-input recovery
map. Reference: docs/reference/legacy-adapters.md.

Importing any module here runs nothing: no process, no socket, no argument parsing
and no environment read. A client only runs a command when it is called, through the
runner it was given. Tests use :mod:`haynes_studio.adapters.fakes`; the real
:class:`~haynes_studio.adapters.runner.SubprocessRunner` is for an authorized live story.

- :mod:`~haynes_studio.adapters.runner`: ``Command``, ``Completed``, ``Runner``,
  ``SubprocessRunner`` and the ``kubectl exec`` targets.
- :mod:`~haynes_studio.adapters.pinned`: the pinned graphs and in-pod snippets.
- :mod:`~haynes_studio.adapters.kokoro`, :mod:`~haynes_studio.adapters.whisper`,
  :mod:`~haynes_studio.adapters.comfyui`: text to speech, transcript, images.
- :mod:`~haynes_studio.adapters.wan_ledger`: the legacy delivery ledger, read-only.
- :mod:`~haynes_studio.adapters.recovery`: the recovery map builder.
"""
