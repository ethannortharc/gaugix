---
order: 6
slug: judge-calibration
title: LLM-as-judge — calibration & bias
summary: A judge is a model doing a task. It has known biases, and the worst is grading its own work.
tags: [judge, bias, calibration]
---

Using a model to grade a model is genuinely useful and genuinely unreliable. The
useful part is that it scales reading. The unreliable part is that a judge is
just another model, with all the failure modes you are trying to measure.

Treat it as an instrument that needs calibration, not an oracle.

## Self-preference is the big one

Models systematically prefer text produced by themselves or by models in their
own family. Not by a little — the effect is large enough to reorder a
leaderboard.

Which makes the default failure mode obvious and expensive: **if you do not
configure a judge, Gaugix falls back to grading with the executor under test.**
Every model marks its own homework, and the ranking you get is partly a ranking
of self-flattery.

Fix: set a default judge in Settings, and prefer one that is not competing in the
comparison at all. If you must use a competitor as judge, say so in the report —
the methodology footer does this automatically.

## Verbosity bias

Judges reward length. A long answer that restates the question, hedges, and adds
a summary will beat a correct two-sentence answer more often than it should.

Fix: say so in the rubric ("length is not a criterion"), and prefer anchors
phrased as *does the answer contain X* rather than *how thorough is it*.

## Position bias

When a judge sees two answers, it favours one position — usually the first.
Gaugix scores one answer at a time against a rubric rather than doing pairwise
comparison, which sidesteps this entirely. If you build pairwise comparison
yourself, run both orders and average.

## Leniency drift

Judges are generous by default. A 1–5 rubric with vague anchors will produce a
distribution crushed against 4 and 5. You can see this immediately: if your mean
score is 85 and your pass rate is 95%, the judge is not discriminating, and the
number is decorative.

Fix: better anchors ([Writing rubrics](/learn/writing-rubrics)), and a threshold
placed where you actually draw the line.

## Calibrate against yourself

The only way to know whether a judge is any good on *your* task is to grade some
of the same items by hand.

1. Add a `human` scorer to a handful of representative cases.
2. Score them in the review queue, without looking at the judge's answer first.
3. Watch the **disagreement counter**. Gaugix records every time your score
   contradicts the judge's.

A disagreement rate under roughly 10% means the judge is tracking your taste and
you can trust it on the rest. Above 25%, the judge is measuring something else —
usually a rubric problem, occasionally a judge that is too small for the task.

Re-check after anything changes: a new judge model, an edited rubric, a new kind
of case.

## Cost is part of the picture

Judge calls are model calls. On a 200-item run with a judge on every case, the
judge can cost more than the thing being evaluated — which is why Gaugix counts
judge tokens in run totals rather than hiding them. Before scaling a judge to a
large set, check what one run costs.

A cheap judge with a sharp rubric usually beats an expensive judge with a vague
one.

## When not to use a judge at all

If a deterministic assertion can decide the case, it should. A judge asked to
verify that JSON has an `action` field is a slow, expensive, occasionally-wrong
`json_schema` check.
