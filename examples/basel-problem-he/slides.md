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

<!-- say: היום אני רוצה לספר לכם אחד מהסיפורים האהובים עליי בכל המתמטיקה.
     זהו סיפור על סכום שהשתיק את המוחות הגדולים באירופה במשך שמונים וחמש שנה,
     עד שמתמטיקאי צעיר פתר אותו בטיעון של אלגנטיות יוצאת דופן.
     זוהי בעיית Basel. -->

---

# A Simple Question

What happens when you add up the reciprocals of the perfect squares?

$$\frac{1}{1} + \frac{1}{4} + \frac{1}{9} + \frac{1}{16} + \frac{1}{25} + \cdots$$

In modern notation:

$$\sum_{n=1}^{\infty} \frac{1}{n^2} = \ ?$$

<!-- say: הנה השאלה. קחו כל מספר שלם בריבוע — אחד, ארבע, תשע, שש עשרה,
     עשרים וחמש, וכן הלאה — הפכו כל אחד מהם, וחברו את כולם.
     האם הסכום האינסופי הזה מתכנס? ואם כן, למה? -->

---

# The Challenge (1650)

**Pietro Mengoli**, a mathematician in Bologna, posed this problem in 1650.

The sum converges (by comparison with $\int_1^\infty x^{-2}\,dx = 1$). The partial sums creep toward something near **1.6449**...

But *what* is this number, exactly?

<!-- say: הבעיה הוצגה לראשונה על ידי Pietro Mengoli ב-1650.
     הסכום מתכנס, וניתן לראות זאת על ידי השוואה עם האינטגרל של אחד חלקי x בריבוע.
     אם מחברים את מאה האיברים הראשונים, מקבלים בערך 1.6349.
     אלף איברים — 1.6439. הסכום מתקרב בבירור למשהו בסביבות 1.6449.
     אבל מהו המספר הזה? האם הוא שורש של פולינום כלשהו?
     לוגריתם של משהו? אף אחד לא מצא ביטוי סגור. -->

---

# The Challenge (1650)

Even Jakob Bernoulli, one of the greatest mathematicians of his era, publicly admitted defeat in 1689:

> "If anyone finds and communicates to us that which thusfar
> has eluded our efforts, great will be our gratitude."
>
> — Jakob Bernoulli, 1689

<!-- say: אפילו Jakob Bernoulli, אחד המתמטיקאים הגדולים של תקופתו,
     הודה בתבוסה בפומבי ב-1689, וכתב: -->

<!-- say(voice=narrator): "אם מישהו ימצא ויעביר לנו את מה שעד כה חמק
     מהמאמצים שלנו, גדולה תהיה הכרת התודה שלנו." -->

---

# Enter Leonhard Euler (1735)

The problem remained open for **85 years**.

Then, in Saint Petersburg, a young mathematician from Basel named **Leonhard Euler** found the answer:

$$\sum_{n=1}^{\infty} \frac{1}{n^2} = \frac{\pi^2}{6}$$

$\pi$? In a sum that has nothing to do with circles?

<!-- say: במשך שמונים וחמש שנה הבעיה נותרה פתוחה.
     ואז, ב-1734, צעיר בן עשרים ושבע בשם Leonhard Euler,
     שעבד באקדמיה למדעים בסנט פטרבורג, מצא את התשובה.
     הוא הציג את ההוכחה שלו בשנה שלאחר מכן.
     הסכום שווה ל-π בריבוע חלקי שש. זה היה מדהים.
     π הוא היחס בין היקף המעגל לקוטרו.
     למה הוא מופיע בסכום של הופכי ריבועים? אין שום מעגל באופק.
     הרשו לי להראות לכם את הטיעון המקורי של Euler.
     הוא לא לגמרי רגורוזי לפי הסטנדרטים המודרניים,
     אבל האינטואיציה כל כך משכנעת שהתוצאה התקבלה מיידית,
     והפערים נסגרו במהלך המאה שלאחר מכן. -->

---

# Step 1: Start with $\sin(x)$

We know the Taylor series for sine:

$$\sin(x) = x - \frac{x^3}{3!} + \frac{x^5}{5!} - \frac{x^7}{7!} + \cdots$$

<!-- say: ההוכחה של Euler מתחילה עם משהו שאולי לא ציפיתם לו: פונקציית הסינוס.
     אנחנו מכירים את טור Taylor של סינוס x.
     הוא שווה ל-x פחות x בשלישית חלקי שלוש עצרת,
     ועוד x בחמישית חלקי חמש עצרת, וכן הלאה. -->

---

# Step 1: Start with $\sin(x)$

We know the Taylor series for sine:

$$\sin(x) = x - \frac{x^3}{3!} + \frac{x^5}{5!} - \frac{x^7}{7!} + \cdots$$

Divide both sides by $x$ (for $x \neq 0$, this is dividing a limit by a constant, which is valid by the algebraic limit theorem):

$$\frac{\sin(x)}{x} = 1 - \frac{x^2}{6} + \frac{x^4}{120} - \cdots$$

Note the coefficient of $x^2$ on the right: it is $-\frac{1}{6}$.

<!-- say: עכשיו, זכרו שטור אינסופי מוגדר כגבול של סכומים חלקיים.
     לכל x קבוע ושונה מאפס, אנחנו יכולים לחלק את הגבול ב-x,
     כי חלוקת גבול בקבוע שונה מאפס מוצדקת על ידי משפט הגבול האלגברי.
     אז אנחנו מקבלים סינוס x חלקי x שווה אחד פחות x בריבוע חלקי שש,
     ועוד איברים מסדר גבוה יותר.
     שימו לב למקדם של x בריבוע. הוא מינוס שישית.
     המספר הזה עוד יחזור. -->

---

# Step 2: Factor by the roots

Now here is Euler's bold move. The function $\frac{\sin(x)}{x}$ has zeros at $x = \pm\pi, \pm 2\pi, \pm 3\pi, \ldots$

<!-- say: ועכשיו מגיע המהלך הנועז של Euler,
     הצעד שהפך את ההוכחה הזו למפורסמת.
     הפונקציה סינוס x חלקי x מתאפסת כאשר x שווה
     ל-פלוס מינוס π, פלוס מינוס 2π, פלוס מינוס 3π, וכן הלאה. -->

---

# Step 2: Factor by the roots

The function $\frac{\sin(x)}{x}$ has zeros at $x = \pm\pi, \pm 2\pi, \pm 3\pi, \ldots$

Euler treated it like a polynomial and factored it by its roots:

$$\frac{\sin(x)}{x} = \left(1 - \frac{x^2}{\pi^2}\right)\!\left(1 - \frac{x^2}{4\pi^2}\right)\!\left(1 - \frac{x^2}{9\pi^2}\right)\cdots$$

> **Assumes:** An entire function is determined by its zeros (up to normalization).
> Justified by the Weierstrass factorization theorem (1876).

<!-- say: Euler חשב באנלוגיה: אם לפולינום יש שורשים מסוימים,
     אפשר לפרק אותו למכפלה של גורמים, אחד לכל שורש.
     הוא יישם את אותו היגיון על סינוס x חלקי x,
     למרות שזו לא פולינום אלא טור אינסופי.
     הוא כתב את הפונקציה כמכפלה אינסופית,
     שבה כל גורם מתאים לזוג שורשים.
     זו הייתה הנחה, לא הוכחה.
     ההצדקה הרגורוזית באה הרבה יותר מאוחר,
     עם משפט הפירוק של Weierstrass מ-1876.
     אבל תראו מה קורה עכשיו. -->

---

# Step 3a: How to read the $x^2$ coefficient from a product

Consider just **three** factors — write $a_k = \frac{1}{k^2\pi^2}$ for short:

$$(1 - a_1 x^2)(1 - a_2 x^2)(1 - a_3 x^2)$$
$$= 1 - (a_1 + a_2 + a_3)\,x^2 + (\text{terms in } x^4, x^6)$$

Each $x^2$ contribution comes from picking $-a_k x^2$ from **one** factor and $1$ from the rest. Cross-terms (picking $x^2$ from two or more factors) yield $x^4$ or higher.

So the $x^2$ coefficient is just $-(a_1 + a_2 + a_3)$.

<!-- say: לפני שנתמודד עם המכפלה האינסופית, בואו נראה למה זה עובד עבור מכפלה סופית.
     קחו רק שלושה גורמים. כל גורם נראה כמו אחד פחות a-k כפול x בריבוע.
     כשמכפילים אותם, איבר x בריבוע נוצר רק כאשר בוחרים
     את החלק מינוס a-k כפול x בריבוע מגורם אחד בדיוק,
     ואת האחד מכל שאר הגורמים.
     אם בוחרים את חלק ה-x בריבוע משני גורמים או יותר,
     מקבלים x בחזקת ארבע או יותר.
     אז המקדם של x בריבוע הוא פשוט הסכום
     a-1 ועוד a-2 ועוד a-3, עם סימן מינוס. -->

---

# Step 3b: Apply to the infinite product

The same logic applies to the full product (assuming it converges absolutely and can be expanded as a power series):

$$\prod_{n=1}^{\infty}\left(1 - \frac{x^2}{n^2\pi^2}\right) = 1 - \left(\sum_{n=1}^{\infty}\frac{1}{n^2\pi^2}\right)x^2 + \cdots$$

The $x^2$ coefficient is:

$$-\left(\frac{1}{\pi^2} + \frac{1}{4\pi^2} + \frac{1}{9\pi^2} + \cdots\right) = -\frac{1}{\pi^2}\sum_{n=1}^{\infty}\frac{1}{n^2}$$

> **Assumes:** The infinite product converges absolutely and can be expanded as a power series, with coefficients computed term-by-term as for finite products.

<!-- say: עכשיו נרחיב למכפלה האינסופית. באותו היגיון בדיוק,
     המקדם של x בריבוע הוא סכום כל ה-a-k עם סימן מינוס.
     זה נותן לנו מינוס אחד חלקי π בריבוע
     ועוד אחד חלקי ארבע π בריבוע
     ועוד אחד חלקי תשע π בריבוע, וכן הלאה.
     אפשר להוציא גורם משותף של אחד חלקי π בריבוע,
     ונשארים בדיוק עם הסכום המסתורי שלנו.
     עכשיו, הרחבת הטיעון הסופי למכפלה אינסופית דורשת
     שהמכפלה תתכנס באופן מוחלט ותוכל להיפרש כטור חזקות.
     זה אכן נכון כאן, אבל לא הוכח בזמנו של Euler.
     בהנחה שזה מתקיים, חילוץ המקדם של x בריבוע עובד
     בדיוק כמו במכפלה סופית. -->

---

# Step 4: The punchline

From the Taylor series:

$$\frac{\sin(x)}{x} = 1 \mathbin{\color{e94560}{- \frac{1}{6}}} \, x^2 + \cdots$$

<!-- say: עכשיו נשווה. טור Taylor אמר לנו שהמקדם של x בריבוע הוא מינוס שישית. -->

---

# Step 4: The punchline

From the Taylor series:

$$\frac{\sin(x)}{x} = 1 \mathbin{\color{e94560}{- \frac{1}{6}}} \, x^2 + \cdots$$

From the product:

$$\frac{\sin(x)}{x} = 1 \mathbin{\color{e94560}{- \frac{1}{\pi^2}\sum_{n=1}^{\infty}\frac{1}{n^2}}} \, x^2 + \cdots$$

<!-- say: המכפלה האינסופית אמרה לנו שהמקדם של x בריבוע הוא
     מינוס אחד חלקי π בריבוע כפול הסכום שלנו. -->

---

# Step 4: The punchline

From the Taylor series:

$$\frac{\sin(x)}{x} = 1 \mathbin{\color{e94560}{- \frac{1}{6}}} \, x^2 + \cdots$$

From the product:

$$\frac{\sin(x)}{x} = 1 \mathbin{\color{e94560}{- \frac{1}{\pi^2}\sum_{n=1}^{\infty}\frac{1}{n^2}}} \, x^2 + \cdots$$

These are two power series for the same function, so their coefficients must agree (by uniqueness of power series):

$$\frac{1}{\pi^2}\sum_{n=1}^{\infty}\frac{1}{n^2} = \frac{1}{6}$$

<!-- say: שניהם ייצוגי טורי חזקות של אותה פונקציה אנליטית,
     וייצוג טור חזקות הוא יחיד.
     לכן המקדמים חייבים להיות שווים.
     נשווה אותם ונקבל: אחד חלקי π בריבוע כפול הסכום שווה לשישית. -->

---

# $\displaystyle\sum_{n=1}^{\infty} \frac{1}{n^2} = \frac{\pi^2}{6}$

Multiply both sides by $\pi^2$:

$$1 + \frac{1}{4} + \frac{1}{9} + \frac{1}{16} + \frac{1}{25} + \cdots = \frac{\pi^2}{6} \approx 1.6449\ldots$$

<!-- say: כפלו את שני הצדדים ב-π בריבוע, והנה זה.
     אחד ועוד רבע ועוד תשיעית ועוד אחד חלקי שש עשרה,
     וכן הלאה עד אינסוף, שווה ל-π בריבוע חלקי שש.
     אותו 1.6449 מסתורי שאף אחד לא הצליח לזהות במשך שמונים וחמש שנה
     הוא π בריבוע חלקי שש.
     קבוע המעגל הסתתר בסכום כל הזמן. -->

---

# Why It Matters

Euler's proof was **not rigorous** by modern standards — the factoring step needed Weierstrass's theory of infinite products to justify, over 140 years later (1876).

But the result itself was correct, and it opened the door to a vast landscape.

<!-- say: עכשיו, ההוכחה המקורית של Euler לא הייתה רגורוזית לפי הסטנדרטים המודרניים.
     צעד הפירוק הנועז דרש את תורת המכפלות האינסופיות,
     ש-Karl Weierstrass יפתח רק ב-1876, למעלה מ-140 שנה מאוחר יותר.
     אבל התוצאה עצמה הייתה נכונה,
     והיא פתחה תחום שלם במתמטיקה. -->

---

# Why It Matters

The sum we computed is $\zeta(2)$, a special value of the **Riemann zeta function**:

$$\zeta(s) = \sum_{n=1}^{\infty} \frac{1}{n^s}$$

- Euler himself showed all **even** values $\zeta(2), \zeta(4), \zeta(6), \ldots$ are rational multiples of powers of $\pi$
- But the **odd** values $\zeta(3), \zeta(5), \zeta(7), \ldots$ remain mysterious — no closed forms are known

<!-- say: הסכום שחישבנו הוא ערך מיוחד של מה שנקרא היום פונקציית zeta של Riemann,
     ב-s שווה שתיים.
     Euler עצמו המשיך והראה שכל הערכים הזוגיים של פונקציית zeta —
     zeta של 2, zeta של 4, zeta של 6, וכן הלאה —
     הם כפולות רציונליות של חזקות π.
     אבל הערכים האי-זוגיים — zeta של 3, zeta של 5, zeta של 7 —
     נותרו מסתוריים.
     עד היום, לא ידועים ביטויים סגורים נקיים לאף אחד מהם.
     חלק מהבעיות הפתוחות הגדולות ביותר במתמטיקה
     מתחילות מהסכום היפה הזה. -->

---

# What We Learned

$$1 + \frac{1}{4} + \frac{1}{9} + \frac{1}{16} + \cdots = \frac{\pi^2}{6}$$

- A simple question can hide a profound answer
- The boldness to treat $\sin(x)/x$ as a polynomial was the key insight
- $\pi$ connects geometry and number theory in ways we are still discovering

<!-- say: אז מה למדנו? לפעמים שאלה פשוטה, כזו שאפשר להציג לילד,
     מסתירה תשובה בעלת עומק יוצא דופן.
     הגאונות של Euler לא הייתה רק מיומנות טכנית.
     היא הייתה העזות לנסות משהו שלא הייתה לו סיבה לעבוד,
     והטעם לזהות יופי בתוצאה.
     ובלב הכול נמצא π, אותו קבוע אוניברסלי,
     שמחבר בשקט את הגיאומטריה של מעגלים
     לאריתמטיקה של מספרים שלמים,
     בדרכים שאנחנו עדיין מגלים היום.
     תודה שהצטרפתם אליי למסע הזה
     דרך אחת ההוכחות היפות ביותר במתמטיקה. -->

---

<!-- _class: sources -->

# Sources

- P. Mengoli, *Novae quadraturae arithmeticae, seu de additione fractionum* (Bologna, 1650)
- J. Bernoulli, *Tractatus de seriebus infinitis* (Basel, 1689) — quote per W. Dunham, *Euler: The Master of Us All* (1999)
- L. Euler, "De summis serierum reciprocarum" (E41), presented Dec. 5, 1735, *Commentarii academiae scientiarum Petropolitanae* 7 (1740)
- K. Weierstrass, "Zur Theorie der eindeutigen analytischen Funktionen," *Abhandlungen der Königlichen Akademie der Wissenschaften zu Berlin* (1876)
- R. Apéry, "Irrationalité de $\zeta(2)$ et $\zeta(3)$," *Astérisque* 61 (1979)

<!-- silent -->
