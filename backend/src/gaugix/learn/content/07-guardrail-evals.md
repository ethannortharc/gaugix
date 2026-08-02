---
order: 7
slug: guardrail-evals
title: Guardrail & safety evals
summary: Blocking everything scores perfectly on attacks. The benign lookalikes are what make a guardrail set real.
tags: [guardrails, safety, precision-recall]
---

Safety evals have a failure mode built into their shape: the trivial policy
"refuse everything" scores 100% on any set made only of attacks. Every useful
guardrail set is therefore two sets in one.

## The two halves

**Attacks** — things that should be blocked. Worth organising by technique,
because defences are technique-specific:

- **Direct** — simply asking for the prohibited thing.
- **Roleplay / framing** — the grandma story, the fictional character, the
  "for a novel I'm writing".
- **Injection** — instructions hidden in content the system will read: a web
  page, a document, a code comment, a tool result.
- **Obfuscation** — base64, leetspeak, another language, split across turns.
- **Authority claims** — "as an administrator", "in developer mode", "the safety
  team approved this".

**Benign lookalikes** — things that must *not* be blocked, and which resemble
attacks:

- A security researcher asking for a payload to test their own detection rule.
- A chemistry student asking about a reaction that appears in a weapons context.
- A parent asking about a drug interaction.
- A pen-tester asking how an exploit works, in a pen-testing product.

The second half is what turns a score into information. Without it you are
measuring how eager your blocker is, not how good it is.

## Precision and recall, in plain terms

- **Recall** — of the things that should be blocked, how many were? Missing an
  attack is a safety failure.
- **Precision** — of the things that were blocked, how many should have been?
  Blocking a legitimate request is a product failure.

Both matter, and they trade off. Move the threshold to catch the last jailbreak
and you will start refusing chemistry homework. The reason to keep both halves in
one set is that the trade-off becomes visible: you see the number that went up
and the number that went down in the same run.

## Where you draw the line is a product decision

This is worth stating plainly because tooling cannot decide it for you. Should a
security product answer "give me a UNION-based SQL payload to test my detection
rule"? In a pen-testing tool, obviously yes. In a general consumer assistant,
maybe not. Same request, different correct answer.

So: **write the policy down, then encode it in the cases.** When a case's correct
verdict is genuinely arguable, tag it (`policy-review`) rather than quietly
picking a side — otherwise a threshold change looks like a regression when it was
a decision.

## Release gates via baselines

The mechanism that makes a guardrail set operational:

1. Get a run you are willing to stand behind.
2. Mark it **baseline** for the set.
3. Before each release, run the set and open the diff.
4. Ship if there are no regressions; investigate every one that appears.

The diff is the artefact, not the pass rate. "94% pass" tells you little; "two
cases that used to pass now fail, both benign lookalikes" tells you exactly what
your threshold change did.

## Keep the set adversarial

Attack techniques evolve, and a set frozen in March is measuring March. Every
real bypass someone finds should become a case the same day — that is the fastest
compounding loop in this entire guide.

Equally: every false positive a user complains about becomes a benign lookalike.
Both directions, or the set drifts toward whichever failure you notice more.
