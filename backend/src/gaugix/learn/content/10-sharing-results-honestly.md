---
order: 10
slug: sharing-results-honestly
title: Sharing results honestly
summary: Pretty for style, fair for content. What the exported report includes, and why each part is there.
tags: [reporting, methodology, honesty]
---

An eval result becomes an argument the moment you send it to someone. The
difference between a useful argument and marketing is whether the reader can
check it.

Gaugix's export follows one rule: **pretty for style, fair for content.** The
stylesheet can be as polished as you like. The numbers are the ones the run
produced.

## What the report contains, and why

**Headline metrics** — pass rate, item count, mean score, cost, tokens. Cost
carries a `+` when some call could not be priced, because a total that silently
omits an unknown is a lie by rounding.

**The verdict split, including unscored.** Passed, failed, *and* unscored as its
own segment. An eval tool that folds unscored into either bucket can be made to
look better by breaking its scorers.

**Per-executor breakdown** — pass rate, counts, mean score, cost, latency. Cost
next to quality, always, so nobody has to ask.

**What failed.** Every failing case, by name, collapsible. This is the part that
makes a report checkable: a reader can look at the actual failures instead of
taking the aggregate on trust. It is also the part most tempting to omit.

**A methodology footer**, which names:

- every executor: provider, model id, harness;
- every scorer type that contributed to a verdict;
- **the judge** — and if none was configured, it says outright that models graded
  their own output;
- how many model calls were recorded;
- the definition of pass rate (passed ÷ scored, unscored excluded).

That last item exists because "pass rate" is not standard. Two tools can report
different numbers from identical runs by counting differently, and the only fix
is to print the definition next to the number.

## Self-contained by construction

The export is one HTML file: inline CSS, inline SVG charts, no CDN, no web font,
no remote image. It opens offline, from an email attachment, in five years, on a
laptop with no network. There is a test asserting the file contains no external
references, because this is the kind of property that decays silently.

## What honest reporting asks of you

The tool can only do so much. The rest is yours:

- **Say how many cases.** A percentage without a denominator is not a result.
- **Say what changed.** If you are comparing, say what differed between the two
  sides — and if it was more than one thing, say that too.
- **Do not drop the run you disliked.** Running until you get a good number and
  reporting only that is the most common way honest people mislead themselves.
- **Report your noise floor** when you have measured it. "A 4-point difference,
  and reruns vary by 3" is a much more useful sentence than "a 4-point
  difference".
- **Name the judge.** If a model in the comparison graded the comparison, that
  belongs in the first paragraph, not the appendix.

## The test

Before you send it, ask: **if the reader were skeptical and had access to my
data, would they find anything I did not mention?**

If yes, mention it. That is the whole discipline.
