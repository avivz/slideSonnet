"""Ensure no secrets, API keys, or .env files leak into the git repo."""

from __future__ import annotations

import re
import subprocess


def _tracked_files() -> list[str]:
    """Return list of all git-tracked file paths."""
    result = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
    return [f for f in result.stdout.splitlines() if f]


def _read_text_safe(path: str) -> str | None:
    """Read a file as UTF-8, returning None for binary files."""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (UnicodeDecodeError, OSError):
        return None


# ---- .env files must never be tracked ----


def test_no_dotenv_files_tracked():
    """No .env files should be tracked (only .env.example is OK)."""
    dotenv_files = [f for f in _tracked_files() if f.endswith("/.env") or f == ".env"]
    assert dotenv_files == [], f".env files tracked in git: {dotenv_files}"


def test_gitignore_excludes_dotenv():
    """.gitignore at repo root must exclude .env."""
    with open(".gitignore") as f:
        lines = [line.strip() for line in f if not line.startswith("#")]
    assert ".env" in lines, ".env not found in .gitignore"


def test_template_gitignore_excludes_dotenv():
    """The scaffolded .gitignore template must also exclude .env."""
    with open("src/slidesonnet/templates/gitignore.txt") as f:
        lines = [line.strip() for line in f if not line.startswith("#")]
    assert ".env" in lines, ".env not found in template gitignore"


# ---- No real API key values in tracked files ----

# ElevenLabs keys look like: sk_<40+ hex chars>
_REAL_KEY_PATTERNS = [
    re.compile(r"sk_[0-9a-f]{32,}"),  # ElevenLabs production key
    re.compile(r"sk-[A-Za-z0-9]{20,}"),  # OpenAI-style key
    re.compile(r"ELEVENLABS_API_KEY=[^\s]{10,}"),  # Inline assignment with real-looking value
]

# Known safe values that should NOT trigger alerts
_SAFE_VALUES = {
    "your_api_key_here",
    "test-key",
    "test-key-123",
    "sk-test-key",
    "sk-xxx-your-key",
}


def test_no_real_api_keys_in_tracked_files():
    """No tracked file should contain a real-looking API key."""
    violations: list[str] = []
    for path in _tracked_files():
        content = _read_text_safe(path)
        if content is None:
            continue
        for pattern in _REAL_KEY_PATTERNS:
            for match in pattern.finditer(content):
                value = match.group()
                # Strip surrounding assignment syntax for comparison
                bare = value.split("=", 1)[-1] if "=" in value else value
                if bare not in _SAFE_VALUES:
                    violations.append(f"{path}: {value[:40]}...")
    assert violations == [], "Possible API keys in tracked files:\n" + "\n".join(violations)


# ---- No .env.example contains real keys ----


def test_env_example_has_only_placeholders():
    """All .env.example files must use placeholder values, not real keys."""
    env_examples = [f for f in _tracked_files() if f.endswith(".env.example")]
    for path in env_examples:
        content = _read_text_safe(path)
        assert content is not None, f"Cannot read {path}"
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                _key, value = line.split("=", 1)
                assert value in _SAFE_VALUES or value == "", (
                    f"{path}: suspicious value in env example: {line}"
                )


# ---- env.txt template must not contain real keys ----


def test_env_template_has_only_placeholders():
    """The env.txt template shipped in the package must use placeholders."""
    content = _read_text_safe("src/slidesonnet/templates/env.txt")
    assert content is not None
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            _key, value = line.split("=", 1)
            assert value in _SAFE_VALUES or value == "", (
                f"env.txt template has suspicious value: {line}"
            )
