"""Tests for the init command."""

from slidesonnet.init import init_blank, init_example, init_from


def test_blank_creates_structure(tmp_path):
    target = tmp_path / "myproject"
    init_blank(target)

    assert (target / "lecture01.yaml").exists()
    assert (target / ".gitignore").exists()
    assert (target / ".env").exists()
    assert (target / "pronunciation" / "terms.md").exists()
    assert (target / "01-intro" / "slides.md").exists()


def test_blank_gitignore_protects_env(tmp_path):
    target = tmp_path / "myproject"
    init_blank(target)

    gitignore = (target / ".gitignore").read_text()
    assert ".env" in gitignore
    assert "cache/" in gitignore


def test_blank_env_has_placeholder(tmp_path):
    target = tmp_path / "myproject"
    init_blank(target)

    env = (target / ".env").read_text()
    assert "your_api_key_here" in env


def test_blank_playlist_has_comments(tmp_path):
    target = tmp_path / "myproject"
    init_blank(target)

    playlist = (target / "lecture01.yaml").read_text()
    assert "//" in playlist  # has documentation comments


def test_blank_slides_have_say(tmp_path):
    target = tmp_path / "myproject"
    init_blank(target)

    slides = (target / "01-intro" / "slides.md").read_text()
    assert "<!-- say:" in slides


def test_example_creates_full_project(tmp_path):
    target = tmp_path / "myproject"
    init_example(target)

    assert (target / "lecture01.yaml").exists()
    assert (target / ".gitignore").exists()
    assert (target / ".env").exists()
    assert (target / "pronunciation" / "cs-terms.md").exists()
    assert (target / "01-intro" / "slides.md").exists()
    assert (target / "02-definitions" / "slides.md").exists()


def test_example_pronunciation_has_entries(tmp_path):
    target = tmp_path / "myproject"
    init_example(target)

    pron = (target / "pronunciation" / "cs-terms.md").read_text()
    assert "**Dijkstra**" in pron
    assert "DYKE-struh" in pron


def test_example_playlist_has_two_modules(tmp_path):
    target = tmp_path / "myproject"
    init_example(target)

    from slidesonnet.playlist import parse_playlist

    _, entries = parse_playlist(target / "lecture01.yaml")
    assert len(entries) == 2


def test_from_copies_config(tmp_path):
    # Create a source project
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_playlist = source_dir / "lecture.yaml"
    source_playlist.write_text(
        "title: Source Project\n"
        "tts:\n"
        "  backend: elevenlabs\n"
        "pronunciation:\n"
        "  - pron/terms.md\n"
        "modules:\n"
        "  - intro/slides.md\n"
    )
    # Create pronunciation file
    pron_dir = source_dir / "pron"
    pron_dir.mkdir()
    (pron_dir / "terms.md").write_text("**Euler**: OY-ler\n")

    # Create .env
    (source_dir / ".env").write_text("ELEVENLABS_API_KEY=sk-real-key\n")

    # Init from source
    target = tmp_path / "target"
    init_from(target, source_playlist)

    # Check config was copied
    playlist = (target / "lecture01.yaml").read_text()
    assert "Source Project" in playlist
    assert "elevenlabs" in playlist

    # Check pronunciation was copied
    assert (target / "pron" / "terms.md").exists()
    assert "OY-ler" in (target / "pron" / "terms.md").read_text()

    # Check .env values were blanked
    env = (target / ".env").read_text()
    assert "sk-real-key" not in env
    assert "your_value_here" in env

    # Check .gitignore created
    assert (target / ".gitignore").exists()


def test_from_copies_dict_format_pronunciation(tmp_path):
    """init_from handles dict-format pronunciation (per-backend)."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_playlist = source_dir / "lecture.yaml"
    source_playlist.write_text(
        "title: Source Project\n"
        "pronunciation:\n"
        "  shared:\n"
        "    - pron/names.md\n"
        "  piper:\n"
        "    - pron/piper-hacks.md\n"
        "modules:\n"
        "  - intro/slides.md\n"
    )
    # Create pronunciation files
    pron_dir = source_dir / "pron"
    pron_dir.mkdir()
    (pron_dir / "names.md").write_text("**Euler**: OY-ler\n")
    (pron_dir / "piper-hacks.md").write_text("**Knuth**: kuh-NOOTH\n")

    target = tmp_path / "target"
    init_from(target, source_playlist)

    assert (target / "pron" / "names.md").exists()
    assert (target / "pron" / "piper-hacks.md").exists()
    assert "OY-ler" in (target / "pron" / "names.md").read_text()
    assert "kuh-NOOTH" in (target / "pron" / "piper-hacks.md").read_text()
