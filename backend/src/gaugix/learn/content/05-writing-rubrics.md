---
order: 5
slug: writing-rubrics
title: Writing rubrics
summary: A rubric is a definition, not an adjective. Anchor every scale point in something observable.
tags: [judge, rubrics, authoring]
---

A rubric tells a judge what to look for. Most rubrics fail because they describe
quality with superlatives instead of describing what the text must contain.

## The failure mode

> Score 1–5 on how good the explanation is. 5 is excellent, 1 is poor.

This produces 4s. Always 4s. The judge has no way to distinguish a 3 from a 4, so
it lands on "slightly above average" for almost everything, and your scores carry
no information.

## Anchor every point

An anchor says what an answer at that level *does*, in terms you could check
yourself:

> **5** — Names the specific defect (the channel is never closed), explains why
> it causes the symptom (receivers block forever on an open channel), and gives
> the fix in code.
> **4** — Names the defect and gives the fix, but the causal explanation is
> vague or partly wrong.
> **3** — Identifies the right area but not the defect; the fix is incomplete.
> **2** — Plausible-sounding but addresses a different problem.
> **1** — Wrong, or no diagnosis at all.

Now a 3 and a 4 mean different things, and two different judges — or a judge and
you — can agree on which one applies.

## Rules that make anchors work

**Describe content, not impression.** "Mentions the missing `close`" is checkable;
"shows deep understanding" is not.

**Make the levels mutually exclusive.** If an answer can be both a 3 and a 4,
the judge picks the higher one, and your scale compresses upward.

**Put the hard distinction where you care.** If everything you evaluate is
already decent, do not waste four levels on failure. Spend them on the
distinction that matters: complete vs. nearly-complete.

**Say what does not count.** "Length is not a criterion. A correct two-sentence
answer scores the same as a correct two-page one." Without that line, judges
reward verbosity — see [Judge calibration & bias](/learn/judge-calibration).

## Choose the smallest scale that works

Binary is underrated. If the real question is "is this acceptable?", a
pass/fail rubric is easier to write, easier to agree on, and produces a metric
you can act on. Reach for 1–5 when you genuinely need to rank partial credit,
and set a `pass_threshold` so the verdict is still crisp.

A 0–100 scale is almost always false precision. Nobody can define the difference
between 73 and 76.

## Test the rubric before trusting it

Take three answers you already have opinions about — one good, one borderline,
one bad — and check whether the rubric produces the scores you expect. If the
borderline one comes out as a 5, the anchors are too generous. This takes five
minutes and saves you from a hundred meaningless scores.

Then keep checking: score a handful by hand in the review queue and watch the
disagreement rate. A rubric is not finished when you write it; it is finished
when a judge using it agrees with you.

## Reuse rubrics

If ten cases share an expectation, they should share a rubric — define it once
on the set and let cases inherit it. Ten near-identical rubrics drift apart, and
then a change in results might be a change in the model or a change in one copy
of the wording.
