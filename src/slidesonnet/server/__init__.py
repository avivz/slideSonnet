"""The editor's HTTP backend: services, jobs, events, and the ``/api/v1`` routes.

UI-framework-free. During the frontend migration it mounts on NiceGUI's FastAPI
app (one process, one origin); once NiceGUI is gone it mounts on a plain
FastAPI app. See ``docs/frontend-migration.md``.
"""
