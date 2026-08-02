---
order: 3
slug: choosing-scorers
title: Choosing scorers
summary: Deterministic first, judge when you must, human when only judgement works. Each costs something different.
tags: [scoring, judge, cost]
---

The most common mistake in eval design is reaching for an LLM judge immediately.
Judges are the most expensive, slowest and least reliable option, and for a
surprising fraction of real cases you do not need one.

## The order to try

**1. Deterministic assertions.** `contains`, `not_contains`, `regex`,
`json_schema`. Free, instant, perfectly reproducible, and they never change their
mind. If your expectation can be written as "the output must contain a closed
channel" or "the output must be valid JSON with an `action` field", stop here.

**2. A Python scorer.** When the check is real logic — parse the output, run the
generated function, compare a computed value — write it as code. Still free,
still deterministic, and arbitrarily precise. A scorer that actually executes the
model's code and checks the answer is worth more than any rubric about whether
the code "looks correct".

**3. An LLM judge.** For things that genuinely require reading: is this
explanation clear, is this translation idiomatic, does this answer the question
that was asked. Costs money per item, has biases (see
[Judge calibration & bias](/learn/judge-calibration)), and needs its own
verification.

**4. A human — you.** For the cases where you do not yet trust any automation, or
where the judgement *is* the product. Slow and unscalable, which is exactly why
it should be reserved for the few cases that earn it.

## The trade-off table

| | Cost | Speed | Reproducible | Handles nuance |
|---|---|---|---|---|
| Assertion | free | instant | exactly | no |
| Python | free | fast | exactly | some |
| Judge | per item | slow | approximately | yes |
| Human | your time | slowest | no | yes |

"Reproducible" is the column people underweight. A judge at temperature 0 still
drifts across model versions, which means a score change might be your system
changing or the judge changing. An assertion never has that ambiguity.

## Combining them

Cases usually want more than one scorer. A good pattern for a coding case:

- a **required** assertion that the answer contains the actual fix (`close(`),
- a **required** judge scoring the explanation against a rubric, weight 2,
- an **optional** regex checking for a code fence, so you can see formatting
  discipline without letting it fail the case.

The verdict comes from the required ones; the numbers come from all of them.

## Signals you picked wrong

- **Your judge always says 4/5.** The rubric is not discriminating. Either the
  cases are too easy or the anchors are too vague.
- **An assertion fails on answers you would accept.** It is testing wording, not
  behaviour. Loosen it or move to a judge.
- **You keep overriding the judge in review.** Read your disagreement rate — that
  is what the review queue's counter is for. A judge you routinely overrule is
  costing money to produce a number you ignore.
- **Everything passes.** Add the case that failed last week. A set where
  everything passes is measuring nothing.

## The cheapest useful thing

If you take one habit from this chapter: **write the assertion first, even if you
also want a judge.** It costs nothing, it catches the gross failures immediately,
and when the judge and the assertion disagree you have learned something about
one of them.
