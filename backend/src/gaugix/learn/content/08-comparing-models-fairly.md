---
order: 8
slug: comparing-models-fairly
title: Comparing models fairly
summary: Change one thing. Disclose the rest. Most model comparisons are actually harness comparisons.
tags: [comparison, methodology, cost]
---

A comparison is only meaningful if the thing you changed is the thing you are
measuring. That sounds obvious and is violated constantly.

## Change one thing

If model A ran last month on a slightly older version of the prompt and model B
ran today, the difference between them includes the prompt edit. Gaugix
snapshots case text and scoring into the run for exactly this reason: you can
check whether two runs were measuring the same thing.

The clean comparison is one run containing both executors. Same cases, same
scoring, same moment.

## The harness is part of the system

The same model reached through a plain chat completion and through an agent
harness with tools is not the same system. It sees different context, takes
different numbers of steps, and can do things the bare model cannot.

This is why Gaugix binds results to executors rather than models. When you report
"Claude scored 82%", the honest version is "Claude, via this harness, with these
params, scored 82%" — and the report's methodology footer prints all three.

## Disclose the parameters

Temperature, max tokens, reasoning effort, system prompt. All of these move
results, and a comparison that varies one silently is not a comparison.

The productive version of this is deliberate: make reasoning effort an
**executor override**, so "gpt-5 at low effort" and "gpt-5 at high effort" are two
rows in the leaderboard. Now the question "is high effort worth 3× the cost on my
tasks?" has an answer with a number attached.

## Cost-normalised quality

The most useful column in a leaderboard is usually not pass rate. It is pass rate
next to cost.

A model that scores 4 points lower for a fifth of the price is often the correct
choice, and you will never notice it if you sort by quality alone. Latency
belongs in the same conversation for anything interactive.

Gaugix reports cost per executor including judge spend, and flags totals as a
floor when some call could not be priced — a "+" after the number means "at
least this much". Never treat an unpriced call as free.

## Contamination

Public benchmark scores may reflect training-set exposure rather than capability.
Your own cases, written from your own work and never published, do not have this
problem. That is one of the strongest arguments for a private set.

If you do use public data, prefer recent items, and be suspicious of a model that
is unusually good at exactly one benchmark.

## Nondeterminism

Two runs of the same model on the same cases will not produce identical results
unless everything is pinned, and often not even then. Before concluding that A
beats B, ask whether the gap is bigger than the noise — see
[Statistics you actually need](/learn/statistics-you-need).

The cheap check: run the same executor twice and look at the diff. If a handful
of cases flip on their own, that is your noise floor, and any difference smaller
than it is not a finding.

## A fair-comparison checklist

- Same cases, same scoring, ideally the same run.
- Params recorded and reported for every executor.
- The judge is not one of the models being ranked.
- Cost and latency shown next to quality.
- Noise floor known before differences are interpreted.
