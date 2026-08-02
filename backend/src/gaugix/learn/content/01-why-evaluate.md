---
order: 1
slug: why-evaluate
title: Why evaluate
summary: Vibes do not survive a model upgrade. A small set of cases you actually care about is an asset that compounds.
tags: [foundations, motivation]
---

Most people choose a model the same way: try three prompts, notice one feels
better, ship it. That works exactly until something changes — a new model
version, a prompt edit, a temperature tweak, a provider silently rerouting your
traffic. Then you are back to trying three prompts, and you have no idea whether
the thing you changed made anything better.

The problem is not that intuition is bad. It is that intuition does not persist.
You cannot diff it, you cannot hand it to a colleague, and you cannot ask it
whether last Tuesday's version was worse.

## What an eval actually buys you

An eval is a written-down expectation. That sounds bureaucratic until you notice
what becomes possible once expectations are written down:

- **You can answer "did this get worse?"** — not by remembering, but by running
  the same twenty cases and looking at what changed.
- **You can compare models on your work** rather than on someone else's
  benchmark. MMLU tells you nothing about whether a model handles your API's
  error messages well.
- **You can pay attention to cost.** "Good enough and 8× cheaper" is a real
  answer, and you cannot find it without measuring both sides.
- **You can delegate the check.** A run is a thing anyone on the team can start.

## Small and yours beats big and public

Public benchmarks are useful for the field and mostly useless for your product.
They test general capability on tasks nobody in your codebase has. Worse, they
leak: a benchmark that has been public for two years is in the training data,
and a high score on it may mean nothing at all.

Twenty cases drawn from your own bug reports, support tickets and code reviews
will tell you more than any leaderboard. They are not contaminated, they are
weighted toward what you actually do, and every failure is one you care about.

## The compounding part

The first run of a small set is worth something. The tenth is worth much more,
because by then the set has absorbed ten rounds of "oh, it does *that* now" —
each surprise turned into a case. Sets grow at exactly the moments you learn
something, which is why they end up encoding what your team knows about the
problem.

This is also why the cheapest time to start is now, with five cases, badly. A
set that exists gets better. A set you are planning to write properly next
quarter does not.

## What to expect

Evals do not produce certainty. They produce a **number attached to a written
definition**, which is a much more useful thing to argue about than a feeling.
When someone says "the new model is worse at our refactors", the interesting
question is which cases regressed — and that is a question with an answer.

Start with the failure you most recently had to explain to someone. That is your
first case.
