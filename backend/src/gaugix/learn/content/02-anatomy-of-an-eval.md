---
order: 2
slug: anatomy-of-an-eval
title: Anatomy of an eval
summary: Case, set, executor, run, scorer, verdict — the six words everything else is built from.
tags: [foundations, terminology]
---

Every eval system reinvents the same vocabulary with different names. Here is
the one Gaugix uses, and — more usefully — what each piece is *for*.

## Case

One input, one expectation. A case has a **title** (what behaviour it checks),
an **input** (the messages sent to the model), an optional **reference** (what a
good answer looks like, for a judge or a human to compare against), and
**scoring** (how to decide whether the answer was acceptable).

The unit is deliberately small. "Handles our API errors" is not a case; "returns
a 429 with a Retry-After hint when rate limited" is.

## Set

An ordered collection of cases. Sets are how you say "this group of expectations
belongs together" — a guardrail suite, a Go refactoring benchmark, a set of
tricky translations.

A set can carry **default scoring**, inherited by any case that does not define
its own. That is what makes a fifty-case guardrail set practical: the rule is
written once, and only the exceptions carry their own scorer.

## Executor

A **model profile** (which model, which provider, which generation params) paired
with a **harness** (how it is called: a direct chat completion, a CLI agent, a
simulator). Every result binds to an executor, not to a model — because the same
model behind two different harnesses is genuinely two different systems, and a
comparison that blurred them would be lying.

This is also why "the same model at low and high reasoning effort" is two
executors, and can be ranked against itself.

## Run

One execution of {sets} × {executors}. A run **snapshots** everything at the
moment it is planned — the case text, the scoring config, the model params — so
a result stays interpretable after you edit the case. Six months later you can
still ask "what exactly was this measuring?" and get an answer.

Runs produce **items**: one per (case, executor) pair. An item is the atom of
everything downstream — filtering, comparison, diffing.

## Scorer and verdict

A scorer looks at the output and returns a judgement. There are several kinds
(next chapter), but they all produce the same shape: pass/fail, optionally a
number, and a **rationale** saying why.

An item's **verdict** is: every *required* scorer passed. Three things about
that rule matter more than they look:

- **Optional scorers do not decide.** Mark a scorer `required: false` when you
  want the number without giving it a veto.
- **A scorer that errored counts as a failure** when it is required — with the
  error recorded as its rationale. A broken regex should be loud, not silently
  neutral.
- **No resolved scorers means no verdict**, not a pass. An item nothing checked
  is "done, unscored", and it is excluded from pass rate entirely. Counting it
  as passing would let you reach 100% by deleting your scorers.

## Attempt

One actual call, with its tokens, cost, latency and errors. An item can have
several — retries, or a rerun after you fixed something. Old attempts are marked
superseded rather than deleted, so the history of "what did we try" survives.

## Putting it together

> A **run** executes each **case** in a **set** against each **executor**,
> producing an **item** whose **attempt** is graded by **scorers** into a
> **verdict**.

Everything in the rest of this guide is a decision about one of those six words.
