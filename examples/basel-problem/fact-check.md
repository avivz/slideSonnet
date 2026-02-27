# Fact-Check Report: The Basel Problem Presentation

## Process

The presentation was first drafted from memory, then every factual claim was
extracted and verified through three independent channels:

1. **Web research** — four parallel research agents checked historical claims
   against primary and secondary sources (MacTutor biographies, Euler Archive,
   ProofWiki, Wikipedia, Dunham's *Euler: The Master of Us All*).

2. **Symbolic computation** — a temporary Python/SymPy environment verified all
   mathematical claims:
   - Taylor series of sin(x)/x via `sympy.series()`
   - ζ(2) = π²/6 via `sympy.zeta(2)`
   - Infinite product x² coefficient via symbolic expansion of N-term products
   - Partial sums S₁₀₀ and S₁₀₀₀ via direct floating-point summation
   - Date arithmetic for Euler's age

3. **Cross-referencing** — where sources disagreed (notably on the 1644 vs 1650
   date), the original publication was traced to resolve the conflict.

## Claims Verified Correct

| # | Claim | Verification |
|---|-------|--------------|
| 1 | Pietro Mengoli was a mathematician in Bologna | MacTutor biography: born 1626 in Bologna, professor at University of Bologna for 39 years |
| 2 | Jakob Bernoulli discussed the problem in 1689 | *Tractatus de seriebus infinitis* (Basel, 1689), Proposition XVII |
| 3 | S₁₀₀ ≈ 1.6349 | Python: `sum(1/n**2 for n in range(1,101))` = 1.6349839002 |
| 4 | S₁₀₀₀ ≈ 1.6439 | Python: `sum(1/n**2 for n in range(1,1001))` = 1.6439345667 |
| 5 | π²/6 ≈ 1.6449 | Python: `math.pi**2/6` = 1.6449340668; SymPy: `zeta(2) == pi**2/6` confirmed |
| 6 | Taylor series: sin(x)/x = 1 − x²/6 + x⁴/120 − ... | SymPy: `series(sin(x)/x, x, 0, n=8)` = `1 - x**2/6 + x**4/120 - x**6/5040 + O(x**8)` |
| 7 | sin(x)/x has zeros at ±π, ±2π, ±3π, ... | Standard result (zeros of sin(x), excluding x=0) |
| 8 | Infinite product x² coefficient = −(1/π²)∑1/n² | SymPy: expanded 5-term product, x² coeff = −5269/(3600π²), matching −(1/π²)(1+1/4+1/9+1/16+1/25) |
| 9 | Euler was working in Saint Petersburg | Euler arrived May 17, 1727; became senior chair of mathematics 1733; remained until 1741 |
| 10 | Euler was raised in Basel | Born in Basel April 15, 1707; childhood in nearby Riehen; schooled and university in Basel |
| 11 | Karl Weierstrass (first name) | Full name: Karl Theodor Wilhelm Weierstrass (1815–1897) |
| 12 | Basel problem = ζ(2) | Standard definition: ζ(s) = ∑1/nˢ; at s=2 this is ∑1/n² |
| 13 | No known closed forms for ζ(3), ζ(5), ζ(7) | Apéry proved ζ(3) irrational (1979) but no closed form known; even less is known for ζ(5), ζ(7) |

## Corrections Made

### 1. Mengoli's date: 1644 → 1650

**Original claim:** "Pietro Mengoli posed this problem in 1644."

**Finding:** The 1644 date appears in some secondary sources (including
Wikipedia) but likely confuses two different works by Mengoli. The book
where the Basel problem actually appears is *Novae quadraturae arithmeticae,
seu de additione fractionum*, which has a publication date of **1650**
according to the Internet Archive digitized copy and the MacTutor biography.
ProofWiki notes "some sources say 1644" but gives 1650.

**Correction:** Changed to 1650 throughout (slide text, narration, and
derived "years open" count).

### 2. Bernoulli quote: "admiration" → "gratitude"

**Original claim:**
> "If someone should succeed in finding what till now has eluded the efforts
> of others, great will be my admiration."

**Finding:** The standard English translation, per William Dunham's
*Euler: The Master of Us All* (1999), reads:
> "If anyone finds and communicates to us that which thusfar has eluded our
> efforts, great will be our gratitude."

Three errors in the original: "someone should succeed in finding" vs "anyone
finds and communicates to us"; "efforts of others" vs "our efforts"; and
"my admiration" vs "our gratitude."

**Correction:** Replaced with the Dunham translation.

### 3. Years the problem remained open: 91 → 85

**Original claim:** "The problem remained open for 91 years."

**Finding:** This was arithmetic from the wrong start date: 1735 − 1644 = 91.
With the corrected date: 1735 − 1650 = **85**.

**Correction:** Changed to 85 in slide text and narration.

### 4. Location: "in Basel" → "in Saint Petersburg"

**Original claim (slide 4):** "Then, in Basel, Switzerland, a young
mathematician named Leonhard Euler found the answer."

**Finding:** Euler left Basel in April 1727 and was working at the
Saint Petersburg Academy of Sciences when he solved the problem in 1734 and
presented it on December 5, 1735. He never returned to Basel. The problem
is *named* after Basel (because both the Bernoullis and Euler were from
there), but the solution was found in Saint Petersburg.

**Correction:** Changed to "in Saint Petersburg, a young mathematician from
Basel."

### 5. Euler's age: 28 → 27 (at discovery)

**Original claim:** "a twenty-eight year old solved it"

**Finding:** Euler was born April 15, 1707. He found the solution during
1734, when he was **27**. The formal presentation was December 5, 1735,
when he was **28**. Saying "28" is defensible for the presentation date but
misleading for the discovery.

**Correction:** Narration now says "twenty-seven year old" and clarifies he
"found the answer" in 1734 and "presented his proof the following year."

### 6. Weierstrass timeline: "a century later" → "over 140 years later"

**Original claim:** "the factoring step needed Weierstrass's theory of
infinite products to justify, a century later"

**Finding:** The Weierstrass factorization theorem was published in 1876
("Zur Theorie der eindeutigen analytischen Funktionen"). The gap from
Euler's 1735 presentation is **141 years**, significantly more than "a
century."

**Correction:** Changed to "over 140 years later (1876)" in slide text and
narration.

### 7. Odd vs even zeta values: made the contrast explicit

**Original claim:** "The still-unsolved mystery of ζ(3), ζ(5), ζ(7), ... —
are they related to π?"

**Finding:** The claim targets the right values (odd), but misses the key
contrast: Euler himself proved that all *even* zeta values are rational
multiples of powers of π. It is specifically the *odd* values where no
such connection is known. Stating the even-value result makes the odd-value
mystery much more striking.

**Correction:** Rewrote the bullet points and narration to state both halves:
even values are all π-related (Euler showed this); odd values remain
mysterious.

## Sources Consulted

- MacTutor History of Mathematics: biographies of [Mengoli](https://mathshistory.st-andrews.ac.uk/Biographies/Mengoli/), [Euler](https://mathshistory.st-andrews.ac.uk/Biographies/Euler/), [Weierstrass](https://mathshistory.st-andrews.ac.uk/Biographies/Weierstrass/)
- Internet Archive: [Mengoli, *Novae quadraturae arithmeticae* (1650)](https://archive.org/details/bub_gb_PrKgVx1LcUUC)
- Euler Archive: [E41 — De summis serierum reciprocarum](http://eulerarchive.maa.org/backup/E041.html)
- W. Dunham, *Euler: The Master of Us All* (MAA, 1999) — Bernoulli quote
- ProofWiki: [Basel Problem Historical Note](https://proofwiki.org/wiki/Basel_Problem/Historical_Note), [Weierstrass Factorization Theorem](https://proofwiki.org/wiki/Weierstrass_Factorization_Theorem)
- Wikipedia: [Basel problem](https://en.wikipedia.org/wiki/Basel_problem), [Apéry's constant](https://en.wikipedia.org/wiki/Ap%C3%A9ry%27s_constant), [Particular values of the Riemann zeta function](https://en.wikipedia.org/wiki/Particular_values_of_the_Riemann_zeta_function)
- SymPy 1.13 for symbolic verification
