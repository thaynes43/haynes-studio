"""The private input import of The Winter Menu (story 846). Reference:
docs/reference/private-input-import.md.

Reads the private inputs the public records name (the recovery map of story 425 and the
E0 motion records of story 457) read-only from the Wan volume, through the read-only
clients of :mod:`haynes_studio.adapters`, publishes each distinct hash once,
create-only, into a store (story 379), and imports it as its existing asset version
under its public source key (stories 382 and 457). Bytes that are not the public hash
are refused and reported, never recorded as the old version.

- :mod:`~haynes_studio.importer.plan`: what to read, from public records only.
- :mod:`~haynes_studio.importer.run`: the import, the dry run and the report.
- :mod:`~haynes_studio.importer.command`: ``python -m haynes_studio.importer``.

Importing any module here runs nothing: no process, no socket, no argument parsing and
no environment read. Only :func:`~haynes_studio.importer.command.main` makes the real
runner, and only for a run that is not a dry run.
"""
