"""Where the voice is silent inside each utterance of a preview track.

The editor follows the spoken word by estimate, spreading an utterance's time
over its words. A clip carries silences of its own, though: the breath at a
comma or full stop, and (Inworld) about half a second of tail. Spread over the
words, those make the estimate run late, worst at the end of the line. So the
silences are found in the built track itself (plain 16-bit PCM, read with
numpy: no extra ffmpeg) and the browser advances only through voiced time.
"""

from __future__ import annotations

import wave
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from slidesonnet.api import SpeechSpan

#: Quieter than this (dB below full scale) counts as silence.
SILENCE_DB = -40.0
#: A silence must last at least this long (s) to count: shorter dips are
#: consonants and word joins, not pauses.
MIN_SILENCE = 0.08
_FRAME = 0.02  # analysis window (s)


def silences_in(track: Path, spans: Sequence[SpeechSpan]) -> list[list[tuple[float, float]]]:
    """Per span, its silent stretches as absolute ``(start, end)`` track times.

    A track that isn't 16-bit PCM WAV yields no silences (the estimate then
    spreads over the whole span, as before) rather than failing the preview.
    """
    try:
        with wave.open(str(track), "rb") as w:
            if w.getsampwidth() != 2:
                return [[] for _ in spans]
            rate, channels = w.getframerate(), w.getnchannels()
            return [_span_silences(w, rate, channels, span) for span in spans]
    except (OSError, EOFError, wave.Error):
        return [[] for _ in spans]


def _span_silences(
    w: wave.Wave_read, rate: int, channels: int, span: SpeechSpan
) -> list[tuple[float, float]]:
    first = max(0, int(span.start * rate))
    count = max(0, min(int(span.end * rate), w.getnframes()) - first)
    hop = max(1, int(_FRAME * rate))
    frames = count // hop
    if frames == 0:
        return []
    w.setpos(first)
    raw = np.frombuffer(w.readframes(frames * hop), dtype="<i2").astype(np.float32)
    mono = raw.reshape(-1, channels).mean(axis=1)[: frames * hop].reshape(frames, hop)
    rms = np.sqrt((mono**2).mean(axis=1))
    quiet = rms < 32768.0 * 10 ** (SILENCE_DB / 20)
    out: list[tuple[float, float]] = []
    run_start: int | None = None
    for i, q in enumerate([*quiet.tolist(), False]):  # the sentinel closes a trailing run
        if q and run_start is None:
            run_start = i
        elif not q and run_start is not None:
            if (i - run_start) * _FRAME >= MIN_SILENCE:
                start = (first + run_start * hop) / rate
                out.append((start, min(span.end, (first + i * hop) / rate)))
            run_start = None
    return out
