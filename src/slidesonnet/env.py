"""Load API keys from a ``.env`` file into the process environment.

Cloud TTS keys (``ELEVENLABS_API_KEY``, ``INWORLD_API_KEY``) live in a ``.env``
at the project root. The engines read ``os.environ`` directly, but nothing on
the synthesis path loaded the file — only ``slidesonnet doctor`` did — so a key
sitting in ``.env`` was invisible to actual generation. :func:`create_tts` now
calls :func:`load_env`, so every synthesis path (CLI, GUI preview, background
queue) sees the key.
"""

from __future__ import annotations


def load_env() -> None:
    """Load a ``.env`` file (searched from the cwd upward) into ``os.environ``.

    No-op when python-dotenv isn't installed. python-dotenv's default
    ``override=False`` means an already-exported variable is never clobbered, so
    repeated calls are idempotent and a shell export always wins over ``.env``.
    """
    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:
        return
    load_dotenv(find_dotenv(usecwd=True))
