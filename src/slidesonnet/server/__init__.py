"""The editor's HTTP backend: services, jobs, events, and the ``/api/v1`` routes.

UI-framework-free: :func:`slidesonnet.server.app.create_app` builds a plain
FastAPI app that also serves the Vue frontend (one process, one origin).
"""
