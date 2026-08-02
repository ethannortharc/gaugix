---
order: 9
slug: statistics-you-need
title: Statistics you actually need
summary: On twenty cases, a two-point difference is nothing. Here is the small amount of maths that keeps you honest.
tags: [statistics, methodology]
---

You do not need much statistics to run good evals. You need enough to stop
yourself from believing small differences.

## The one number to internalise

On **20 cases**, one case is 5 percentage points.

So a 90% versus 85% result is *one case*. That difference can come from
temperature, from a retry, from nothing at all. It is not evidence.

A rough rule for a pass-rate difference to be worth acting on:

| Cases | Difference worth noticing |
|---|---|
| 20 | ~20 points (4 cases) |
| 50 | ~14 points |
| 100 | ~10 points |
| 500 | ~4 points |

These come from the standard error of a proportion (roughly `√(p(1−p)/n)`,
doubled for a difference of two, doubled again for a 95% interval). Do not
compute it every time — just remember that **small sets only detect large
differences**.

## This is not a reason to give up on small sets

A twenty-case set cannot rank two similar models. It can do something more
valuable: catch the case that broke.

That is a different question, and it does not need statistics. "This specific
case used to pass and now fails" is a fact about one case, and the diff shows you
which one. Regression detection works on small sets precisely because it is not
about the aggregate.

So: **use small sets for diffs, larger sets for rankings.**

## Noise from nondeterminism

Even at temperature 0, models are not perfectly reproducible across time or
infrastructure. Measure your own noise floor rather than assuming it:

1. Run the same executor on the same set twice.
2. Diff the two runs.
3. However many cases flipped, that is your noise.

If three cases flip on a rerun, a three-case improvement means nothing. This
takes one extra run and permanently changes how you read your own numbers.

## Mean score hides its distribution

A mean of 3.4 out of 5 could be every case at 3.4, or half at 5 and half at 1.8.
Those are completely different situations — the second has a bimodal failure mode
worth investigating.

Look at the verdict split, not just the mean. If you have a judge, glance at
whether scores cluster at one value; that usually means the rubric is not
discriminating rather than that the model is uniformly mediocre.

## Unscored is not zero

Gaugix computes pass rate as **passed ÷ scored**, excluding items nothing
resolved. This matters more than it sounds: if a scorer errored on 5 of 20 items,
counting those as failures would report 60% when the honest number is 80% of what
was actually measured, with 5 items unmeasured.

Whenever you see a pass rate, also look at how many items it was computed over.

## What to do with all this

- Do not report a difference smaller than your noise floor.
- Do not rank models on twenty cases.
- Do use twenty cases to catch regressions.
- Do say how many cases a number came from — the exported report does this for
  you.

Then get back to writing cases, which will improve your evals far more than any
statistical refinement.
