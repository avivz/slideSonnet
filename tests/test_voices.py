"""The portable voice layer: deck-level internal voice names mapped per engine.

Covers resolution (``synth.speech_refs``), the load→save round-trip through the
sidecar preamble, and the ``check`` voice-mapping diagnostic.
"""

from __future__ import annotations

from pathlib import Path

from slidesonnet.audio import synth as synth_mod
from slidesonnet.config import Config
from slidesonnet.models import TTSConfig, VoiceConfig
from slidesonnet.narration.model import Deck, PageNarration, Segment


def _voice_deck(**deck_kwargs: object) -> Deck:
    """A two-utterance deck: one names ``guest``, one falls back to default."""
    return Deck(
        pdf_path=Path("x.pdf"),
        sidecar_path=Path("x.narration"),
        pages=["a"],
        narration={
            "a": PageNarration(
                "a",
                [
                    Segment.speech("From the guest.", voice="guest"),
                    Segment.speech("From the default."),
                ],
            )
        },
        voices={
            "lecturer": VoiceConfig("lecturer", {"kokoro": "am_michael", "elevenlabs": "L1"}),
            "guest": VoiceConfig("guest", {"kokoro": "af_bella"}),
        },
        default_voice="lecturer",
        **deck_kwargs,  # type: ignore[arg-type]
    )


def test_resolution_uses_deck_map_and_default() -> None:
    deck = _voice_deck()
    refs = synth_mod.speech_refs(deck, Config(tts=TTSConfig(backend="kokoro")))
    # explicit voice -> guest's kokoro voice; unset -> default 'lecturer' kokoro voice
    assert [r.voice for r in refs] == ["af_bella", "am_michael"]


def test_resolution_follows_active_engine() -> None:
    deck = _voice_deck()
    refs = synth_mod.speech_refs(deck, Config(tts=TTSConfig(backend="elevenlabs")))
    # 'guest' has no elevenlabs voice -> None (engine default); 'lecturer' -> L1
    assert [r.voice for r in refs] == [None, "L1"]


def test_deck_voices_win_over_toml_library() -> None:
    deck = _voice_deck()
    config = Config(
        tts=TTSConfig(backend="kokoro"),
        voices={"guest": VoiceConfig("guest", {"kokoro": "zz_shared"})},
    )
    refs = synth_mod.speech_refs(deck, config)
    assert refs[0].voice == "af_bella"  # deck's guest, not the toml's zz_shared


def test_toml_library_fills_unmapped_deck_names() -> None:
    # a name only defined in the toml library still resolves (shared fallback)
    deck = Deck(
        pdf_path=Path("x.pdf"),
        sidecar_path=Path("x.narration"),
        pages=["a"],
        narration={"a": PageNarration("a", [Segment.speech("Hi.", voice="shared")])},
    )
    config = Config(
        tts=TTSConfig(backend="kokoro"),
        voices={"shared": VoiceConfig("shared", {"kokoro": "af_sky"})},
    )
    refs = synth_mod.speech_refs(deck, config)
    assert refs[0].voice == "af_sky"


def test_voice_layer_survives_save_load(tmp_path: Path) -> None:
    from slidesonnet.deck import load_deck, save_deck

    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    deck = _voice_deck()
    deck.pdf_path = pdf
    deck.sidecar_path = tmp_path / "x.narration"
    save_deck(deck)

    text = deck.sidecar_path.read_text(encoding="utf-8")
    assert "# slidesonnet-format: 2" in text
    assert "default-voice: lecturer" in text
    assert "guest:" in text

    # reload (no PDF read — inject the page id) and the voice layer round-trips
    reloaded, _ = load_deck(pdf, pages=(["a"], []))
    assert reloaded.default_voice == "lecturer"
    assert reloaded.voices["guest"].backend_voices == {"kokoro": "af_bella"}


def test_voice_diagnostics_flag_unmapped_engine() -> None:
    from slidesonnet.diagnostics import voice_diagnostics

    blocks = [
        PageNarration("a", [Segment.speech("Hi.", voice="guest")]),
        PageNarration("b", [Segment.speech("Yo.")]),  # uses the default
    ]
    voices = {
        "lecturer": VoiceConfig("lecturer", {"kokoro": "am_michael", "elevenlabs": "L1"}),
        "guest": VoiceConfig("guest", {"kokoro": "af_bella"}),  # no elevenlabs
    }

    # kokoro maps everything -> no warnings
    assert voice_diagnostics(blocks, voices, "lecturer", "kokoro") == []

    # elevenlabs: 'guest' is unmapped -> exactly one warning, naming guest
    diags = voice_diagnostics(blocks, voices, "lecturer", "elevenlabs")
    assert [d.code for d in diags] == ["voice-unmapped"]
    assert "guest" in diags[0].message and "elevenlabs" in diags[0].message


def test_voice_diagnostics_ignore_raw_ids() -> None:
    from slidesonnet.diagnostics import voice_diagnostics

    # a voice that isn't a named preset is a raw engine id -> never flagged
    blocks = [PageNarration("a", [Segment.speech("Hi.", voice="af_heart")])]
    assert voice_diagnostics(blocks, {}, None, "kokoro") == []
