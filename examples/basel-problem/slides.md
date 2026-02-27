---
marp: true
math: katex
style: |
  section {
    font-family: 'Georgia', serif;
  }
  h1 {
    color: #1a1a2e;
  }
  blockquote {
    border-left: 4px solid #e94560;
    padding-left: 1em;
    font-style: italic;
    color: #555;
  }
---

# The Basel Problem

### A story of an impossible sum, a young genius, and a surprise visit from $\pi$

<!-- say: Today, I want to tell you one of my favorite stories in all of
     mathematics. It is the story of a sum that stumped the greatest
     minds in Europe for eighty-five years, until a young mathematician
     solved it with an argument so bold, it still takes your breath away.
     This is the Basel Problem. -->

---

# A Simple Question

What happens when you add up the reciprocals of the perfect squares?

$$\frac{1}{1} + \frac{1}{4} + \frac{1}{9} + \frac{1}{16} + \frac{1}{25} + \cdots$$

In modern notation:

$$\sum_{n=1}^{\infty} \frac{1}{n^2} = \ ?$$

<!-- say: Here is the question. Take every perfect square, one, four,
     nine, sixteen, twenty-five, and so on, flip each one over, and add
     them all up. Does this infinite sum converge? And if so, to what? -->

---

# The Challenge (1650)

**Pietro Mengoli**, a mathematician in Bologna, posed this problem in 1650.

It was clear the sum converges — each term gets small fast. The partial sums creep toward something near **1.6449**...

But *what* is this number, exactly?

> "If anyone finds and communicates to us that which thusfar
> has eluded our efforts, great will be our gratitude."
>
> — Jakob Bernoulli, 1689

<!-- say: The problem was first posed by Pietro Mengoli in 1650. It was
     easy to see the sum converges. If you add up the first hundred
     terms, you get about 1.6349. A thousand terms, 1.6439. It clearly
     approaches something near 1.6449. But what is this number? Is it
     the root of some polynomial? The logarithm of something? Nobody
     could find a closed form. Even Jakob Bernoulli, one of the greatest
     mathematicians of his era, publicly admitted defeat in 1689. -->

---

# Enter Leonhard Euler (1735)

The problem remained open for **85 years**.

Then, in Saint Petersburg, a young mathematician from Basel named **Leonhard Euler** found the answer:

$$\sum_{n=1}^{\infty} \frac{1}{n^2} = \frac{\pi^2}{6}$$

$\pi$? In a sum that has nothing to do with circles?

<!-- say: For eighty-five years, the problem remained open. Then in 1734,
     a twenty-seven year old named Leonhard Euler, working at the
     Academy of Sciences in Saint Petersburg, found the answer. He
     presented his proof the following year. The sum equals pi squared
     over six. This was shocking. Pi is the ratio of a circle's
     circumference to its diameter. Why would it appear in a sum of
     reciprocal squares? There is no circle anywhere in sight. Let me
     show you Euler's beautiful argument for why this must be true. -->

---

# Step 1: Start with $\sin(x)$

We know the Taylor series for sine:

$$\sin(x) = x - \frac{x^3}{3!} + \frac{x^5}{5!} - \frac{x^7}{7!} + \cdots$$

Divide both sides by $x$:

$$\frac{\sin(x)}{x} = 1 - \frac{x^2}{6} + \frac{x^4}{120} - \cdots$$

Note the coefficient of $x^2$ on the right: it is $-\frac{1}{6}$.

<!-- say: Euler's proof begins with something you might not expect: the
     sine function. We know the Taylor series for sine of x. It equals
     x minus x cubed over three factorial, plus x to the fifth over
     five factorial, and so on. Now divide both sides by x. You get
     sine of x over x equals one minus x squared over six, plus
     higher-order terms. Hold onto that coefficient of x squared. It is
     negative one-sixth. That number is going to come back. -->

---

# Step 2: Factor by the roots

Now here is Euler's bold move. The function $\frac{\sin(x)}{x}$ has zeros at $x = \pm\pi, \pm 2\pi, \pm 3\pi, \ldots$

Euler treated it like a polynomial and factored it by its roots:

$$\frac{\sin(x)}{x} = \left(1 - \frac{x^2}{\pi^2}\right)\!\left(1 - \frac{x^2}{4\pi^2}\right)\!\left(1 - \frac{x^2}{9\pi^2}\right)\cdots$$

<!-- say: Now here is Euler's bold move, the step that made this proof
     famous. The function sine of x over x equals zero whenever x is
     plus or minus pi, plus or minus two pi, plus or minus three pi,
     and so on. Euler reasoned as follows: if a polynomial has certain
     roots, you can factor it as a product of terms, one for each root.
     He applied the same logic to sine of x over x, even though it is
     not a polynomial but an infinite series. He wrote it as an infinite
     product. Each factor in the product corresponds to a pair of roots.
     This was audacious. Euler had no proof that this factoring was
     valid. But watch what happens next. -->

---

# Step 3: Compare the $x^2$ coefficients

Expand the product — only collect the $x^2$ terms:

$$\left(1 - \frac{x^2}{\pi^2}\right)\!\left(1 - \frac{x^2}{4\pi^2}\right)\!\left(1 - \frac{x^2}{9\pi^2}\right)\cdots$$

The $x^2$ coefficient is:

$$-\left(\frac{1}{\pi^2} + \frac{1}{4\pi^2} + \frac{1}{9\pi^2} + \cdots\right) = -\frac{1}{\pi^2}\sum_{n=1}^{\infty}\frac{1}{n^2}$$

<!-- say: Now we expand the infinite product. We do not need to multiply
     everything out. We only care about the x-squared terms. When you
     expand a product of factors that each look like one minus something
     times x squared, the x-squared coefficient is just the sum of all
     those somethings, with a minus sign. So the x-squared coefficient
     of the product is negative one over pi squared, plus one over four
     pi squared, plus one over nine pi squared, and so on. We can
     factor out one over pi squared, and we are left with exactly our
     mystery sum. -->

---

# Step 4: The punchline

From the Taylor series:

$$\frac{\sin(x)}{x} = 1 \mathbin{\color{e94560}{- \frac{1}{6}}} \, x^2 + \cdots$$

From the product:

$$\frac{\sin(x)}{x} = 1 \mathbin{\color{e94560}{- \frac{1}{\pi^2}\sum_{n=1}^{\infty}\frac{1}{n^2}}} \, x^2 + \cdots$$

These are the same function, so the coefficients must match:

$$\frac{1}{\pi^2}\sum_{n=1}^{\infty}\frac{1}{n^2} = \frac{1}{6}$$

<!-- say: Now we just compare. The Taylor series told us the x squared
     coefficient is negative one-sixth. The infinite product told us it
     is negative one over pi squared times our sum. These are two
     representations of the same function, so the coefficients must be
     equal. Set them equal and you get: one over pi squared times the
     sum equals one sixth. -->

---

# $$\sum_{n=1}^{\infty} \frac{1}{n^2} = \frac{\pi^2}{6}$$

Multiply both sides by $\pi^2$:

$$1 + \frac{1}{4} + \frac{1}{9} + \frac{1}{16} + \frac{1}{25} + \cdots = \frac{\pi^2}{6} \approx 1.6449\ldots$$

<!-- say: Multiply both sides by pi squared, and there it is.
     One plus one-fourth plus one-ninth plus one-sixteenth, and so on
     forever, equals pi squared over six. That mysterious 1.6449 that
     nobody could identify for eighty-five years is pi squared over six.
     The circle constant was hiding in the sum all along. -->

---

# Why It Matters

Euler's proof was **not rigorous** by modern standards — the factoring step needed Weierstrass's theory of infinite products to justify, over 140 years later (1876).

But the result opened the door to a vast landscape:

- The **Riemann zeta function**: $\zeta(s) = \sum_{n=1}^{\infty} \frac{1}{n^s}$, with the Basel Problem being $\zeta(2)$
- Euler himself showed all **even** values $\zeta(2), \zeta(4), \zeta(6), \ldots$ are rational multiples of powers of $\pi$
- But the **odd** values $\zeta(3), \zeta(5), \zeta(7), \ldots$ remain mysterious — no closed forms are known

<!-- say: Now, Euler's original proof was not rigorous by modern
     standards. That bold factoring step required the theory of infinite
     products, which Karl Weierstrass would not develop until 1876,
     over 140 years later. But the result itself was correct, and it
     cracked open an entire field of mathematics. The sum we computed is
     a special value of what we now call the Riemann zeta function, at s
     equals two. Euler himself went on to show that all even values of
     the zeta function, zeta of two, zeta of four, zeta of six, and so
     on, are rational multiples of powers of pi. But the odd values,
     zeta of three, zeta of five, zeta of seven, remain mysterious. To
     this day, no clean closed forms are known for any of them. Some of
     the biggest open problems in mathematics trace back to this one
     beautiful sum. -->

---

# What We Learned

$$1 + \frac{1}{4} + \frac{1}{9} + \frac{1}{16} + \cdots = \frac{\pi^2}{6}$$

- A simple question can hide a profound answer
- The boldness to treat $\sin(x)/x$ as a polynomial was the key insight
- $\pi$ connects geometry and number theory in ways we are still discovering

<!-- say: So what did we learn? Sometimes a simple question, one you can
     state to a child, hides an answer of extraordinary depth. Euler's
     genius was not just technical skill. It was the boldness to try
     something that had no right to work, and the taste to recognize
     beauty in the result. And at the heart of it all is pi, that
     universal constant, quietly connecting the geometry of circles to
     the arithmetic of whole numbers in ways we are still discovering
     today. Thank you for joining me on this journey through one of the
     most beautiful proofs in mathematics. -->

---

<!-- _class: sources -->

# Sources

- P. Mengoli, *Novae quadraturae arithmeticae, seu de additione fractionum* (Bologna, 1650)
- J. Bernoulli, *Tractatus de seriebus infinitis* (Basel, 1689) — quote per W. Dunham, *Euler: The Master of Us All* (1999)
- L. Euler, "De summis serierum reciprocarum" (E41), presented Dec. 5, 1735, *Commentarii academiae scientiarum Petropolitanae* 7 (1740)
- K. Weierstrass, "Zur Theorie der eindeutigen analytischen Funktionen," *Abhandlungen der Königlichen Akademie der Wissenschaften zu Berlin* (1876)
- R. Apéry, "Irrationalité de $\zeta(2)$ et $\zeta(3)$," *Astérisque* 61 (1979)

<!-- silent -->
