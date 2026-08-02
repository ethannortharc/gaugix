---
order: 4
slug: writing-good-cases
title: Writing good cases
summary: One behaviour per case, realistic inputs, and the negative cases nobody remembers to write.
tags: [cases, authoring]
---

A case is a claim about how your system should behave. Most bad evals are bad
because the claims are vague, not because the scoring is wrong.

## One behaviour per case

If a case can fail for three reasons, a failure tells you nothing. Split it.

Instead of "handles a malformed request well", write three cases: rejects it with
a 400, names the offending field, does not echo the raw payload back. Now a
regression points at something.

The test is simple: **can you name what a failure would mean, in one sentence?**
If not, the case is doing too much.

## Realistic inputs

Use text you actually saw. Copy the real support ticket, the real stack trace,
the real customer sentence with its typo intact. Synthetic inputs are cleaner
than reality in exactly the ways that matter — no ambiguity, no missing context,
no weird formatting — which is why models do better on them than they will in
production.

The set that predicts production is the set drawn from production.

## Avoiding ambiguity

Before writing the scorer, answer: **would two competent people agree on whether
a given answer passes?** If not, the case is underspecified, and no scorer will
rescue it.

Common fixes:

- Add a `reference` answer. It does not have to be *the* answer — it anchors what
  you meant.
- Move the ambiguity into the input: "answer in at most three sentences" beats a
  rubric line about brevity.
- Split the ambiguous part into a separate, optional scorer.

## Negative cases are the ones you are missing

Nearly every set is skewed toward "the model should do X". The cases that catch
real regressions are usually the opposite: **the model should not do Y**.

- For a guardrail set: benign requests that *look* like attacks. A blocker that
  blocks everything scores 100% on jailbreaks and is useless.
- For a coding set: a question where the right answer is "this code is already
  correct". Models love to find problems.
- For a retrieval set: a question your documents genuinely cannot answer. The
  correct behaviour is saying so.

A set with no negative cases can only measure eagerness.

## Tagging discipline

Tags are how you slice results later, so choose them for the questions you will
ask: `jailbreak`, `benign-lookalike`, `regression`, `golang`, `customer-facing`.

Two rules that keep tags useful:

- **Tag the property, not the verdict.** `hard` decays; `multi-step` does not.
- **Keep the vocabulary small.** Twelve tags used consistently beat forty used
  once each.

## Growing a set

The best source of new cases is failures you have already had to explain. When
something goes wrong in production, the fix has two parts: the change, and the
case that would have caught it. Writing the second part takes two minutes and is
the entire reason the set is worth anything in six months.

Do not try to write fifty cases up front. Write five, run them, and add one every
time you are surprised.
