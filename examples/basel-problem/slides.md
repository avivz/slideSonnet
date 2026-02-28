---
marp: true
math: katex
theme: basel
---

<!-- _class: title -->

# The Basel Problem

### A story of an impossible sum, a young genius, and a surprise visit from $\pi$

<!-- say: Today, I want to tell you about one of my favorite stories in mathematics: the Basel Problem — a sum that resisted solution for eighty-five years before a young mathematician finally cracked it with a beautifully simple idea. -->

---

# A Simple Question

What happens when you add up the reciprocals of the perfect squares?

$$\frac{1}{1} + \frac{1}{4} + \frac{1}{9} + \frac{1}{16} + \frac{1}{25} + \cdots$$

In modern notation:

$$\sum_{n=1}^{\infty} \frac{1}{n^2} = \ ?$$

<!-- say: Here's the question. Take every perfect square — one, four,
     nine, sixteen, twenty-five, and so on — flip each one over, and add
     them all up. Does this infinite sum converge? And if it does...
     to what? -->

---

# The Challenge (1650)

**Pietro Mengoli**, a mathematician in Bologna, posed this problem in 1650.

The sum converges (by comparison with $\int_1^\infty x^{-2}\,dx = 1$). The partial sums creep toward something near **1.6449**...

But *what* is this number, exactly?

<!-- say: The problem was first posed by Pietro Mengoli in 1650. Now,
     the sum does converge — you can check that by comparing it with the
     integral of one over x squared. Add up the first hundred terms, you
     get about 1.6349. A thousand terms? 1.6439. It's clearly approaching
     something near 1.6449. But what is this number? Is it the root of
     some polynomial? The logarithm of something? Nobody could figure
     it out. -->

---

# The Challenge (1650)

Even Jakob Bernoulli, one of the greatest mathematicians of his era, publicly admitted defeat in 1689:

> "If anyone finds and communicates to us that which thusfar
> has eluded our efforts, great will be our gratitude."
>
> — Jakob Bernoulli, 1689

<!-- say: Even Jakob Bernoulli, one of the greatest mathematicians of
     his era, publicly gave up in 1689. He wrote: -->

<!-- say(voice=bernoulli): "If anyone finds and communicates to us that
     which thusfar has eluded our efforts, great will be our
     gratitude." -->

---

# Enter Leonhard Euler

The problem remained open for **85 years**.

Then, in 1734 in Saint Petersburg, a young mathematician from Basel named **Leonhard Euler** found the answer.

<!-- say: For eighty-five years, nobody could solve it. Then in 1734,
     a twenty-seven year old named Leonhard Euler, working at the
     Academy of Sciences in Saint Petersburg, found the answer. He
     presented his proof the following year. -->

---

# Enter Leonhard Euler

$$\sum_{n=1}^{\infty} \frac{1}{n^2} = \frac{\pi^2}{6}$$

$\pi$? In a sum that has nothing to do with circles?

<!-- say: The sum equals pi squared over six. And that was shocking.
     Pi is the ratio of a circle's circumference to its diameter —
     why on earth would it show up in a sum of reciprocal squares?
     There's no circle anywhere in sight. Let me show you Euler's
     original argument. It's not fully rigorous by modern standards,
     but the intuition is so compelling that everyone accepted it
     right away, and the gaps got filled in over the following
     century. -->

---

# Step 1: Start with $\sin(x)$

We know the Taylor series for sine:

$$\sin(x) = x - \frac{x^3}{3!} + \frac{x^5}{5!} - \frac{x^7}{7!} + \cdots$$

<!-- say: Euler's proof starts with something you might not expect —
     the sine function. We know the Taylor series for sine of x: it's
     x minus x cubed over three factorial, plus x to the fifth over
     five factorial, and so on. -->

---

# Step 1: Start with $\sin(x)$

We know the Taylor series for sine:

$$\sin(x) = x - \frac{x^3}{3!} + \frac{x^5}{5!} - \frac{x^7}{7!} + \cdots$$

Divide both sides by $x$ (for $x \neq 0$, this is dividing a limit by a constant, which is valid by the algebraic limit theorem):

$$\frac{\sin(x)}{x} = 1 - \frac{x^2}{6} + \frac{x^4}{120} - \cdots$$

<!-- say: Now remember, an infinite series is just a limit of partial
     sums. For any fixed nonzero x, we can divide that limit by x —
     that's justified by the algebraic limit theorem. So we get sine
     of x over x equals one minus x squared over six, plus
     higher-order terms. -->

---

# Step 1: Start with $\sin(x)$

$$\frac{\sin(x)}{x} = 1 - \frac{x^2}{6} + \frac{x^4}{120} - \cdots$$

Note the coefficient of $x^2$ on the right: it is $-\frac{1}{6}$.

<!-- say: Hold onto that coefficient of x squared — it's negative
     one-sixth. That number is going to come back. -->

---

# Step 2: Factor by the roots

Now here is Euler's bold move. The function $\frac{\sin(x)}{x}$ has zeros at $x = \pm\pi, \pm 2\pi, \pm 3\pi, \ldots$

<!-- say: Now here's Euler's bold move — the step that made this proof
     famous. The function sine of x over x equals zero whenever x is
     plus or minus pi, plus or minus two pi, plus or minus three pi,
     and so on. -->

---

# Step 2: Factor by the roots

The function $\frac{\sin(x)}{x}$ has zeros at $x = \pm\pi, \pm 2\pi, \pm 3\pi, \ldots$

Euler treated it like a polynomial and factored it by its roots:

$$\frac{\sin(x)}{x} = \left(1 - \frac{x^2}{\pi^2}\right)\!\left(1 - \frac{x^2}{4\pi^2}\right)\!\left(1 - \frac{x^2}{9\pi^2}\right)\cdots$$

> **Assumes:** An entire function is determined by its zeros (up to normalization).
> Justified by the Weierstrass factorization theorem (1876).

<!-- say: Euler reasoned by analogy. If a polynomial has certain roots,
     you can factor it as a product of terms, one for each root. He
     applied the same logic to sine of x over x — even though it's
     not a polynomial, it's an infinite series. He wrote it as an
     infinite product, where each factor corresponds to a pair of
     roots. Now, this was an assumption, not a proof. The rigorous
     justification came much later, with the Weierstrass factorization
     theorem of 1876. So what do we get? -->

---

# Step 3a: How to read the $x^2$ coefficient from a product

Consider just **three** factors — write $a_k = \frac{1}{k^2\pi^2}$ for short:

$$(1 - a_1 x^2)(1 - a_2 x^2)(1 - a_3 x^2)$$
$$= 1 - (a_1 + a_2 + a_3)\,x^2 + (\text{terms in } x^4, x^6)$$

Each $x^2$ contribution comes from picking $-a_k x^2$ from **one** factor and $1$ from the rest. Cross-terms (picking $x^2$ from two or more factors) yield $x^4$ or higher.

So the $x^2$ coefficient is just $-(a_1 + a_2 + a_3)$.

<!-- say: Before we tackle the infinite product, let's see why this
     works for a finite one. Take just three factors. Each factor looks
     like one minus a-k times x squared. When we multiply them out, an
     x-squared term only shows up when we pick the negative a-k
     x-squared piece from exactly one factor and the one from every
     other factor. Pick the x-squared piece from two or more factors,
     and you get x to the fourth or higher. So the x-squared
     coefficient is just the sum, a-one plus a-two plus a-three,
     with a minus sign. -->

---

# Step 3b: Apply to the infinite product

$$\prod_{n=1}^{\infty}\left(1 - \frac{x^2}{n^2\pi^2}\right) = 1 - \left(\sum_{n=1}^{\infty}\frac{1}{n^2\pi^2}\right)x^2 + \cdots$$

The $x^2$ coefficient is:

$$-\left(\frac{1}{\pi^2} + \frac{1}{4\pi^2} + \frac{1}{9\pi^2} + \cdots\right) = -\frac{1}{\pi^2}\sum_{n=1}^{\infty}\frac{1}{n^2}$$

> **Assumes:** Absolute convergence and term-by-term expansion, as for finite products.

<!-- say: Now extend this to the infinite product. By exactly the same
     reasoning, the x-squared coefficient is the sum of all the a-k's
     with a minus sign. That gives us negative one over pi squared,
     plus one over four pi squared, plus one over nine pi squared, and
     so on. Factor out the one over pi squared, and what's left?
     Exactly our mystery sum. Now, extending the finite argument to an
     infinite product does require absolute convergence and a valid
     power series expansion. That's true here, but it wasn't proven in
     Euler's time. Granting that assumption, the extraction works just
     as it does for a finite product. -->

---

# Step 4: The punchline

From the Taylor series:

$$\frac{\sin(x)}{x} = 1 \mathbin{\color{#e94560}{- \frac{1}{6}}} \, x^2 + \cdots$$

<!-- say: Now we compare. The Taylor series told us the x squared
     coefficient is negative one-sixth. -->

---

# Step 4: The punchline

From the Taylor series:

$$\frac{\sin(x)}{x} = 1 \mathbin{\color{#e94560}{- \frac{1}{6}}} \, x^2 + \cdots$$

From the product:

$$\frac{\sin(x)}{x} = 1 \mathbin{\color{#e94560}{- \frac{1}{\pi^2}\sum_{n=1}^{\infty}\frac{1}{n^2}}} \, x^2 + \cdots$$

<!-- say: And the infinite product told us it's negative one over pi
     squared times our sum. -->

---

# Step 4: The punchline

From the Taylor series:

$$\frac{\sin(x)}{x} = 1 \mathbin{\color{#e94560}{- \frac{1}{6}}} \, x^2 + \cdots$$

From the product:

$$\frac{\sin(x)}{x} = 1 \mathbin{\color{#e94560}{- \frac{1}{\pi^2}\sum_{n=1}^{\infty}\frac{1}{n^2}}} \, x^2 + \cdots$$

Coefficients must agree: $\quad\dfrac{1}{\pi^2}\displaystyle\sum_{n=1}^{\infty}\frac{1}{n^2} = \frac{1}{6}$

<!-- say: Both are power series for the same function, and a power
     series representation is unique. So the coefficients have to
     match. Set them equal, and you get: one over pi squared times
     the sum equals one-sixth. -->

---

# $\displaystyle\sum_{n=1}^{\infty} \frac{1}{n^2} = \frac{\pi^2}{6}$

Multiply both sides by $\pi^2$:

$$1 + \frac{1}{4} + \frac{1}{9} + \frac{1}{16} + \frac{1}{25} + \cdots = \frac{\pi^2}{6} \approx 1.6449\ldots$$

<!-- say: Multiply both sides by pi squared, and there it is. One plus
     one-fourth plus one-ninth plus one-sixteenth, and so on forever —
     it equals pi squared over six. That mysterious 1.6449 that nobody
     could pin down for eighty-five years? Pi squared over six. The
     circle constant was hiding in the sum all along. -->

---

# Why It Matters

Euler's proof was **not rigorous** by modern standards — the factoring step needed Weierstrass's theory of infinite products to justify, over 140 years later (1876).

But the result itself was correct, and it opened the door to a vast landscape.

<!-- say: So should we worry that Euler's proof cut corners?
     Mathematicians certainly did. It took over a century before
     Weierstrass provided the tools to make that factoring step
     rigorous. But the answer was never in doubt. Sometimes intuition
     runs ahead of proof — and that gap is where new mathematics
     gets born. -->

---

# Why It Matters

The sum we computed is $\zeta(2)$, a special value of the **Riemann zeta function**:

$$\zeta(s) = \sum_{n=1}^{\infty} \frac{1}{n^s}$$

- Euler himself showed all **even** values $\zeta(2), \zeta(4), \zeta(6), \ldots$ are rational multiples of powers of $\pi$
- But the **odd** values $\zeta(3), \zeta(5), \zeta(7), \ldots$ remain mysterious — no closed forms are known

<!-- say: What we just computed is actually a special value of what we
     now call the Riemann zeta function — at s equals two. Euler himself
     went on to show that all the even values, zeta of two, zeta of
     four, zeta of six, and so on, are rational multiples of powers of
     pi. But the odd values? Zeta of three, zeta of five, zeta of
     seven? Still mysterious. To this day, nobody's found clean closed
     forms for any of them. Some of the biggest open problems in
     mathematics trace right back to this one beautiful sum. -->

---

# What We Learned

$$1 + \frac{1}{4} + \frac{1}{9} + \frac{1}{16} + \cdots = \frac{\pi^2}{6}$$

- A simple question can hide a profound answer
- The boldness to treat $\sin(x)/x$ as a polynomial was the key insight
- $\pi$ connects geometry and number theory in ways we are still discovering

<!-- say: So what did we learn? Sometimes a simple question — one you
     could explain to a child — hides an answer of extraordinary depth.
     Euler's genius wasn't just technical skill. It was the boldness to
     try something that had no right to work, and the taste to recognize
     beauty in the result. And at the heart of it all is pi, quietly
     connecting the geometry of circles to the arithmetic of whole
     numbers in ways we're still discovering today. Thanks for joining
     me on this journey through one of the most beautiful proofs in
     mathematics. -->

---

<!-- _class: sources -->

# Sources

- P. Mengoli, *Novae quadraturae arithmeticae, seu de additione fractionum* (Bologna, 1650)
- J. Bernoulli, *Tractatus de seriebus infinitis* (Basel, 1689) — quote per W. Dunham, *Euler: The Master of Us All* (1999)
- L. Euler, "De summis serierum reciprocarum" (E41), presented Dec. 5, 1735, *Commentarii academiae scientiarum Petropolitanae* 7 (1740)
- K. Weierstrass, "Zur Theorie der eindeutigen analytischen Funktionen," *Abhandlungen der Königlichen Akademie der Wissenschaften zu Berlin* (1876)
- R. Apéry, "Irrationalité de $\zeta(2)$ et $\zeta(3)$," *Astérisque* 61 (1979)

<!-- silent -->
