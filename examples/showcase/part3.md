---
marp: true
math: katex
---

# Math in MARP

Inline math: $E = mc^2$

The Gaussian integral:

$$\int_{-\infty}^{\infty} e^{-x^2}\, dx = \sqrt{\pi}$$

MARP renders math via KaTeX, so you get publication-quality equations in Markdown slides.

<!-- say: MARP supports math rendering via KaTeX. Here we see the famous mass energy equivalence inline, and the Gaussian integral as a display equation. -->

---

# Code Blocks

```python
def fibonacci(n: int) -> list[int]:
    """Return the first n Fibonacci numbers."""
    fibs = [0, 1]
    for _ in range(n - 2):
        fibs.append(fibs[-1] + fibs[-2])
    return fibs[:n]

print(fibonacci(10))
# [0, 1, 1, 2, 3, 5, 8, 13, 21, 34]
```

MARP applies syntax highlighting to fenced code blocks.

<!-- say: MARP applies syntax highlighting to fenced code blocks. Here is a Python function that generates Fibonacci numbers. Code blocks are a great way to present algorithms and examples in your slides. -->

---

# Images

![The Great Wave off Kanagawa](images/great-wave.jpg)

*Hokusai, circa 1831 --- public domain*

<!-- say: You can embed images using standard Markdown syntax. This is The Great Wave off Kanagawa by Hokusai, a public domain woodblock print from around 1831. -->

---

# Pronunciation Dictionaries

slideSonnet loads pronunciation dictionaries to improve TTS output:

```markdown
**Dijkstra**: DYKE-struh
**Knuth**: kuh-NOOTH
**FFmpeg**: F-F-mpeg
```

Dijkstra's algorithm and Knuth's contributions are foundational to computer science.

<!-- say: Pronunciation dictionaries help the TTS engine say names correctly. For example, Dijkstra and Knuth are replaced with phonetic spellings before synthesis. You can define dictionaries for technical terms, people's names, or project-specific jargon. -->

---

# Conclusion

In this showcase you have seen:

* **MARP** and **Beamer** slide formats
<!-- say: That wraps up the slideSonnet showcase. You have seen how it supports both MARP Markdown and Beamer LaTeX slide formats. -->
* Narration via `say` annotations in both formats
<!-- say: You learned to add narration using say comments in MARP and say commands in Beamer. -->
* Voice overrides, silent slides, and skip
<!-- say: We covered voice and pace overrides, silent slides for pauses, and skip to exclude slides from the video. -->
* Fragment animation, math, code, images, and pronunciation
<!-- say: And you saw fragment animation for incremental reveals, math equations, code blocks, images, and pronunciation dictionaries. To build this showcase yourself, run slidesonnet build lecture dot md. Thanks for watching! -->
