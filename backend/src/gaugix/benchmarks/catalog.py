"""The benchmark catalogue: what each public eval is, and what it costs you.

A catalogue entry is mostly *prose*, and deliberately so. Installing a benchmark
is a decision — about licence, about relevance, about whether the number it
produces will mean anything for your model in 2026 — and a row with a name and
an Install button hides all of that. So every entry states, in the user's words
rather than the paper's: what it measures, what a score does *not* tell you,
how Gaugix scores it, and where the file comes from.

`caveats` is the field that earns its keep. Every benchmark here has a real
reason to distrust it — contamination, saturation, judge dependence, an
approximate scorer — and a workbench that presents benchmarks without saying so
is helping you fool yourself (see the Eval Guide, chapter 8).

Nothing here touches the network. `bundled_sample_path` points at real rows
committed to the repo, so every entry is installable and testable offline; the
`source` is what the explicit "install the full set" button reaches for.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gaugix.benchmarks.adapters import ADAPTERS
from gaugix.schemas.cases import CaseIO

SAMPLES_DIR = Path(__file__).parent / "samples"

#: How a source file is fetched and read.
HTTP_JSONL = "jsonl"
HTTP_JSONL_GZ = "jsonl.gz"
HTTP_CSV = "csv"


#: Gaugix reproduces the published method, rule for rule, within the stated
#: deviations. A number from it can reasonably sit next to a published one.
OFFICIAL = "official-compatible"
#: Gaugix runs the benchmark's *data* through a method of its own. The number
#: is meaningful for comparing your own models and is **not** the published
#: metric — it must never be quoted as a leaderboard score.
ADAPTATION = "gaugix-adaptation"


@dataclass(frozen=True, slots=True)
class Method:
    """How faithfully Gaugix reproduces the benchmark's own scoring.

    This exists because "we ran IFEval" and "we ran something IFEval-shaped"
    produce numbers that look identical and mean different things. Every entry
    states which it is, what it does differently, and whether the result is
    comparable to a published score — in the response, not in a footnote.
    """

    fidelity: str
    #: True only when a number from Gaugix is comparable to published results
    #: for the same model. False means "useful for comparing your own runs".
    comparable: bool
    #: Every way this differs from the published method. Never empty.
    deviations: tuple[str, ...]
    #: Bumped when the adapter or scorer changes in a way that moves scores, so
    #: two installs can be told apart. Recorded on every installed set.
    version: str = "1"


@dataclass(frozen=True, slots=True)
class Source:
    """Where the full dataset lives, stated plainly so the user can check it."""

    url: str
    #: How to decode the body: jsonl | jsonl.gz | csv
    encoding: str
    approx_bytes: int
    #: What the user is agreeing to contact when they press "install full".
    host: str
    #: The immutable revision the URL points at — a commit SHA where the host
    #: has one. A `main`-tracking URL silently redefines the benchmark under
    #: you; TruthfulQA lost 27 questions that way (D-050).
    revision: str = ""
    #: SHA-256 of the body at that revision, verified on download. Empty only
    #: for hosts that publish no revision at all.
    sha256: str = ""
    #: Rows expected at that revision, checked after decoding.
    expected_rows: int = 0


@dataclass(frozen=True, slots=True)
class Benchmark:
    slug: str
    name: str
    publisher: str
    year: int
    licence: str
    licence_url: str
    homepage: str
    task: str
    languages: tuple[str, ...]
    #: Cases in the full download. The bundled sample is always much smaller.
    full_size: int
    summary: str
    #: Markdown. What it is and why anyone made it.
    description: str
    #: Markdown. What a score does and does not license you to claim.
    what_it_measures: str
    #: Reasons to distrust the number. Never empty.
    caveats: tuple[str, ...]
    #: How Gaugix scores it, including any approximation.
    scoring_note: str
    bundled_sample_path: str
    method: Method
    source: Source | None = None
    #: True when scoring runs model-written code on this machine.
    requires_code_execution: bool = False
    #: True when scoring spends money on a judge model.
    requires_judge: bool = False
    tags: tuple[str, ...] = ()
    paper: str | None = None
    #: Set when the dataset's licence differs from the repository's — the
    #: commonest trap in this catalogue, and a legal one.
    licence_note: str | None = None

    @property
    def adapter(self) -> Callable[[list[dict[str, Any]]], list[CaseIO]]:
        return ADAPTERS[self.slug]

    def sample_rows(self) -> list[dict[str, Any]]:
        """The rows committed to the repo, in the benchmark's own native shape."""
        import json

        path = SAMPLES_DIR / self.bundled_sample_path
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def sample_cases(self) -> list[CaseIO]:
        return self.adapter(self.sample_rows())


CATALOG: tuple[Benchmark, ...] = (
    Benchmark(
        slug="gsm8k",
        name="GSM8K",
        publisher="OpenAI",
        year=2021,
        licence="MIT",
        licence_url="https://github.com/openai/grade-school-math/blob/master/LICENSE",
        homepage="https://github.com/openai/grade-school-math",
        paper="https://arxiv.org/abs/2110.14168",
        task="Grade-school maths word problems",
        languages=("en",),
        full_size=1319,
        summary="1,319 word problems needing two to eight arithmetic steps.",
        description=(
            "Grade School Math 8K is a set of maths problems written by human "
            "problem writers, each solvable with a short chain of basic "
            "arithmetic. It became the standard first check on whether a model "
            "can hold a multi-step calculation together, because the individual "
            "steps are trivial and only the *sequence* is hard.\n\n"
            "This is the test split, which is what people mean when they quote a "
            "GSM8K number."
        ),
        what_it_measures=(
            "Whether a model can carry an intermediate result through several "
            "steps without losing it. It says nothing about harder mathematics, "
            "about proof, or about arithmetic on large numbers — every answer "
            "here is reachable with a handful of operations a ten-year-old knows."
        ),
        caveats=(
            "Heavily contaminated. GSM8K predates most current training corpora "
            "and appears in many of them; a high score may be recall, not "
            "reasoning. Treat it as a floor, not a differentiator.",
            "Saturated at the top. Frontier models score in the high 90s, so the "
            "gap between two good models is inside the noise of 1,319 items.",
            "Only the final number is checked. A right answer reached by wrong reasoning passes.",
        ),
        scoring_note=(
            "A Python scorer compares the last number in the answer against the "
            "gold value, ignoring thousands separators so `1,000` and `1000` "
            "match. Deterministic and free — no judge model is involved."
        ),
        bundled_sample_path="gsm8k.jsonl",
        method=Method(
            fidelity=OFFICIAL,
            comparable=True,
            deviations=(
                "The answer is taken as the last number in the response rather than "
                "the text after the `####` marker — the flexible-extract convention, "
                "which scores slightly higher than strict-match on chatty models.",
            ),
        ),
        source=Source(
            url=(
                "https://raw.githubusercontent.com/openai/grade-school-math/"
                "b0bb162abedc65e1fdd8e93ed090fd7598ee68bc/grade_school_math/data/test.jsonl"
            ),
            encoding=HTTP_JSONL,
            approx_bytes=749_738,
            host="raw.githubusercontent.com",
            revision="b0bb162abedc65e1fdd8e93ed090fd7598ee68bc",
            sha256="3730d312f6e3440559ace48831e51066acaca737f6eabec99bccb9e4b3c39d14",
            expected_rows=1319,
        ),
        tags=("math", "reasoning", "deterministic"),
    ),
    Benchmark(
        slug="mt-bench",
        name="MT-Bench",
        publisher="LMSYS",
        year=2023,
        licence="Apache-2.0",
        licence_url="https://github.com/lm-sys/FastChat/blob/main/LICENSE",
        homepage="https://github.com/lm-sys/FastChat/tree/main/fastchat/llm_judge",
        paper="https://arxiv.org/abs/2306.05685",
        task="Open-ended instruction following, graded by a judge model",
        languages=("en",),
        full_size=80,
        summary="80 open-ended questions across eight categories, scored 1–10 by a judge.",
        description=(
            "MT-Bench is small on purpose. Eighty questions spread over writing, "
            "roleplay, reasoning, maths, coding, extraction, STEM and humanities, "
            "each written to have no single right answer — so the only way to "
            "score it is judgement.\n\n"
            "It is the benchmark that made LLM-as-judge respectable: the paper "
            "that introduced it also measured how well a strong judge agrees "
            "with human graders, and found the agreement comparable to the "
            "agreement between two humans."
        ),
        what_it_measures=(
            "Whether answers are actually useful to a person: on topic, correct, "
            "detailed enough, and not padded. Because a model grades it, what "
            "you are really measuring is *your judge's opinion* of the answer — "
            "which is informative, and is not the same thing as quality."
        ),
        caveats=(
            "Judge-dependent. Change the judge model and the ranking can change. "
            "Pin one judge for any comparison you intend to trust.",
            "Judges favour their own family's outputs and reward length. Gaugix "
            "warns when a model would grade itself; heed it here above all.",
            "Only the first turn of each two-turn conversation is evaluated. The "
            "follow-up depends on the model's own answer and cannot be replayed "
            "from a file — it is kept in each case's notes.",
            "Eighty items is a small sample. A 3-point gap on a 1–10 scale over "
            "80 cases is not a result; see the Eval Guide, chapter 9.",
        ),
        scoring_note=(
            "An LLM judge scores 1–10 against MT-Bench's single-answer rubric, "
            "passing at 7. This costs money on every run — pick a judge on the "
            "Settings page before installing."
        ),
        bundled_sample_path="mt-bench.jsonl",
        method=Method(
            fidelity=ADAPTATION,
            comparable=False,
            deviations=(
                "Only the first turn of each two-turn conversation is evaluated. "
                "Official MT-Bench scores both turns and reports their average, so a "
                "Gaugix number is not an MT-Bench score.",
                "The reference-guided judge the official harness uses for the maths, "
                "coding and reasoning categories is not applied — every category is "
                "graded with the single-answer rubric.",
            ),
        ),
        source=Source(
            url=(
                "https://raw.githubusercontent.com/lm-sys/FastChat/"
                "b494d0c6b4e7935f1764f8439e75da3e66beccc7/"
                "fastchat/llm_judge/data/mt_bench/question.jsonl"
            ),
            encoding=HTTP_JSONL,
            approx_bytes=48_929,
            host="raw.githubusercontent.com",
            revision="b494d0c6b4e7935f1764f8439e75da3e66beccc7",
            sha256="119565adbab82227089cefdb44c8d7e2cf04dc0a0ec233634c82e7d4e2a944f7",
            expected_rows=80,
        ),
        requires_judge=True,
        tags=("open-ended", "judge", "chat"),
    ),
    Benchmark(
        slug="ifeval",
        name="IFEval",
        publisher="Google Research",
        year=2023,
        # The repository is Apache-2.0; the *dataset* is CC BY 4.0, which is what
        # you are bound by when you redistribute the questions.
        licence="CC BY 4.0",
        licence_url="https://creativecommons.org/licenses/by/4.0/",
        licence_note=(
            "The dataset is CC BY 4.0. Apache-2.0 covers the google-research "
            "repository's source, not the instructions themselves."
        ),
        homepage="https://github.com/google-research/google-research/tree/master/instruction_following_eval",
        paper="https://arxiv.org/abs/2311.07911",
        task="Verifiable instruction following",
        languages=("en",),
        full_size=541,
        summary="541 prompts whose constraints a program can check exactly.",
        description=(
            "IFEval asks for things a computer can verify: write at least 300 "
            "words, use no commas, wrap the answer in quotes, include exactly "
            "four bullet points. No judge, no rubric, no opinion — either the "
            "output has 300 words or it does not.\n\n"
            "That makes it the cheapest honest signal in this catalogue, and a "
            "useful control: if a model scores well on judged benchmarks and "
            "badly here, the judge may be rewarding style over compliance."
        ),
        what_it_measures=(
            "Whether a model does exactly what it was told, including the boring "
            "parts. It measures compliance, not quality — an answer can satisfy "
            "every constraint and be useless."
        ),
        caveats=(
            "Strict by construction. Near-misses fail: 299 words is a fail when "
            "300 were asked for, which is the point but reads harshly.",
            "This is the **strict** metric only. The official harness also reports "
            "a 'loose' variant that strips markdown and opening pleasantries before "
            "checking, and loose scores run several points higher.",
            "Constraint-following is trainable in a way that does not generalise. "
            "A high score does not imply the model follows instructions it has "
            "not seen this shape of.",
        ),
        scoring_note=(
            "A Python scorer implements all 25 of IFEval's instruction verifiers, "
            "following the official rules — including the strict `<` on 'less "
            "than' comparisons and the `***` paragraph divider. Every constraint "
            "must hold to pass; the score also reports the fraction satisfied. "
            "Free and deterministic.\n\n"
            "Three rules depend on NLP components Gaugix approximates rather than "
            "ships, which is why the result is not quotable against published "
            "IFEval numbers — see the deviations above."
        ),
        bundled_sample_path="ifeval.jsonl",
        method=Method(
            # All 25 rules follow the official logic, but three of them lean on
            # NLP components — langdetect and NLTK's Punkt — that Gaugix cannot
            # ship offline and therefore approximates. An approximation that
            # moves scores is not something to quote against a leaderboard, so
            # the claim is withdrawn rather than qualified (D-054).
            fidelity=ADAPTATION,
            comparable=False,
            version="2",
            deviations=(
                "**Not comparable with published IFEval scores.** All 25 official "
                "verifiers are implemented and follow the official rules, but three "
                "depend on NLP components Gaugix approximates rather than ships. "
                "Use it to compare your own models, not to quote a number.",
                "Sentence counting approximates NLTK's Punkt tokeniser with a "
                "punctuation split, which differs on abbreviations like “Dr.”. This "
                "affects `length_constraints:number_sentences`.",
                "Language identification uses the script and, for languages sharing "
                "one, a function-word profile, rather than langdetect. This affects "
                "`language:response_language` — which returns the case *unscored* "
                "rather than guessing when the evidence is thin — and the English "
                "half of `change_case:english_lowercase` and `english_capital`.",
                "Word tokenisation is a regular expression, not NLTK. Hyphenated "
                "words count as one word as they do officially, but contractions "
                "split differently. This affects `change_case:capital_word_frequency` "
                "and `length_constraints:number_words`.",
                "Prompt-level and instruction-level **strict** accuracy only. The "
                "official harness also publishes 'loose' variants, which run several "
                "points higher.",
            ),
        ),
        source=Source(
            url=(
                "https://raw.githubusercontent.com/google-research/google-research/"
                "26d8ccdab6fec61b5c83ad6327ea8bda9e580288/"
                "instruction_following_eval/data/input_data.jsonl"
            ),
            encoding=HTTP_JSONL,
            approx_bytes=207_111,
            host="raw.githubusercontent.com",
            revision="26d8ccdab6fec61b5c83ad6327ea8bda9e580288",
            sha256="67ffeee0fcb87c317c5b08a2de85557b4a7e96ada6178aa645b4954fe4b53d49",
            expected_rows=541,
        ),
        tags=("instruction-following", "deterministic"),
    ),
    Benchmark(
        slug="truthfulqa",
        name="TruthfulQA",
        publisher="Lin, Hilton & Evans",
        year=2021,
        licence="Apache-2.0",
        licence_url="https://github.com/sylinrl/TruthfulQA/blob/main/LICENSE",
        homepage="https://github.com/sylinrl/TruthfulQA",
        paper="https://arxiv.org/abs/2109.07958",
        task="Resisting common misconceptions",
        languages=("en",),
        # 790, not the 817 of the paper: the maintainers removed questions after
        # publication. The pinned revision below is what that number describes.
        full_size=790,
        summary="790 questions people commonly get wrong, where imitation is the trap.",
        description=(
            "Every question here is one where the popular answer is false: "
            "misconceptions, conspiracies, superstitions, misremembered history. "
            "A model trained to imitate human text has learned the wrong answer "
            "from humans, so fluency actively works against it.\n\n"
            "Each question ships with the set of answers judged truthful and the "
            "set judged false, and Gaugix hands both to the judge."
        ),
        what_it_measures=(
            "Whether a model repeats a plausible falsehood it absorbed from "
            "training data. Crucially, a correct refusal counts as truthful — "
            "the benchmark rewards not asserting things you cannot support."
        ),
        caveats=(
            "Adversarially selected. These questions were chosen *because* models "
            "got them wrong, so the absolute score is meaningless — only the "
            "comparison between models on the same set is informative.",
            "The published paper describes 817 questions; the repository now holds "
            "790. A score over this set is not comparable to a 2021 paper number.",
            "Old and widely discussed, so the specific items are likely in training data by now.",
            "Truthfulness and informativeness trade off: a model that answers "
            "'I don't know' to everything scores well here and is useless.",
            "Judge-dependent and therefore not free.",
        ),
        scoring_note=(
            "An LLM judge scores 0 or 1 for truthfulness, with the question's own "
            "truthful and false answer lists embedded in the rubric so the judge "
            "grades against the benchmark's ground truth rather than its own beliefs."
        ),
        bundled_sample_path="truthfulqa.jsonl",
        method=Method(
            fidelity=ADAPTATION,
            comparable=False,
            deviations=(
                "Truthfulness only. The official metric is the *product* of "
                "truthfulness and informativeness — which is what stops "
                "'I don't know' from scoring perfectly — and Gaugix does not "
                "compute informativeness.",
                "Graded by a general-purpose judge, not by the fine-tuned "
                "GPT-judge models the paper calibrated against human raters.",
                "The multiple-choice tasks (MC1/MC2) that most leaderboards report "
                "are not run; this is the generation task.",
            ),
        ),
        source=Source(
            url=(
                "https://raw.githubusercontent.com/sylinrl/TruthfulQA/"
                "f6be04e52bbcb41d4d20daee6358231d4a5015d2/TruthfulQA.csv"
            ),
            encoding=HTTP_CSV,
            approx_bytes=503_550,
            host="raw.githubusercontent.com",
            revision="f6be04e52bbcb41d4d20daee6358231d4a5015d2",
            sha256="b8d8ef1e12f98b4f2a9f47abc9765da0640b182b6c5d9b92f0c1a1f2f1e02e5c",
            expected_rows=790,
        ),
        requires_judge=True,
        tags=("factuality", "safety", "judge"),
    ),
    Benchmark(
        slug="simpleqa",
        name="SimpleQA",
        publisher="OpenAI",
        year=2024,
        licence="MIT",
        licence_url="https://github.com/openai/simple-evals/blob/main/LICENSE",
        homepage="https://github.com/openai/simple-evals",
        paper="https://arxiv.org/abs/2411.04368",
        task="Short-answer factuality",
        languages=("en",),
        full_size=4326,
        summary="4,326 short factual questions with a single verifiable answer.",
        description=(
            "Short questions with exactly one correct, checkable answer — who "
            "won which award in which year, when a paper was published. Every "
            "item was written so that two independent annotators agreed on the "
            "answer, and questions were kept only if strong models got them "
            "wrong.\n\n"
            "The design goal was a factuality benchmark that would not saturate: "
            "at publication, frontier models scored well under 50%."
        ),
        what_it_measures=(
            "Whether a model knows specific facts, and whether it knows when it "
            "does not. The interesting number is not the score but the split "
            "between wrong answers and declined ones — confident wrongness is a "
            "different failure from an admitted gap."
        ),
        caveats=(
            "Adversarially filtered against models available in 2024, so the "
            "absolute number is pessimistic by construction.",
            "Knowledge-cutoff sensitive. Some answers change over time; a model "
            "can be 'wrong' by being newer than the label.",
            "Judge-dependent and, at 4,326 items, the most expensive benchmark "
            "here to run in full. Start with the sample.",
            "English and Western-centric in its choice of facts.",
        ),
        scoring_note=(
            "An LLM judge applies SimpleQA's own three-way grading — CORRECT, "
            "INCORRECT or NOT_ATTEMPTED — and Gaugix passes only CORRECT. The "
            "class is stored as a field on each score, and the run page breaks "
            "the whole run down by it: the share a model declined is the number "
            "that separates a model which knows its limits from one that invents."
        ),
        bundled_sample_path="simpleqa.jsonl",
        method=Method(
            fidelity=ADAPTATION,
            comparable=False,
            deviations=(
                "The official three-way grader prompt is used, but Gaugix reports "
                "accuracy (CORRECT ÷ total) rather than the paper's headline "
                "figures — 'correct given attempted' and the F-score over those "
                "two. Read the NOT_ATTEMPTED share before comparing models.",
                "Graded by whichever judge you configure, not by the ChatGPT "
                "classifier the paper used.",
            ),
        ),
        source=Source(
            url="https://openaipublic.blob.core.windows.net/simple-evals/simple_qa_test_set.csv",
            encoding=HTTP_CSV,
            approx_bytes=2_012_910,
            host="openaipublic.blob.core.windows.net",
            # A blob URL with no revision to pin. The checksum is the only handle
            # on "did this change", so it is the one recorded and verified.
            sha256="feee3f7e7db3617e94e8fcf1977b756ec420ef8568f4e0fcbbe0e92e9d5fc032",
            expected_rows=4326,
        ),
        requires_judge=True,
        tags=("factuality", "judge", "large"),
    ),
    Benchmark(
        slug="humaneval",
        name="HumanEval",
        publisher="OpenAI",
        year=2021,
        licence="MIT",
        licence_url="https://github.com/openai/human-eval/blob/master/LICENSE",
        homepage="https://github.com/openai/human-eval",
        paper="https://arxiv.org/abs/2107.03374",
        task="Python function synthesis, scored by running unit tests",
        languages=("en", "python"),
        full_size=164,
        summary="164 Python functions to complete, each with hidden unit tests.",
        description=(
            "Each case gives a function signature and a docstring; the model "
            "writes the body. Scoring is not an opinion and not a similarity "
            "metric — Gaugix runs the benchmark's own unit tests against "
            "whatever the model produced.\n\n"
            "That makes it the most objective benchmark in this catalogue and "
            "the only one that executes model output."
        ),
        what_it_measures=(
            "Whether a model can write a small, self-contained, correct Python "
            "function. It does not measure anything about real software: no "
            "codebase to navigate, no dependencies, no ambiguity in the spec, "
            "and every task fits in a screen."
        ),
        caveats=(
            "**Scoring executes model-written code on this machine, with your "
            "user's permissions and no sandbox.** Gaugix will not install this "
            "benchmark without an explicit acknowledgement.",
            "Contaminated and saturated. HumanEval is in essentially every code "
            "model's training data and frontier models score above 90%.",
            "164 items with pass/fail scoring means one item is 0.6 points. "
            "Small differences are noise.",
            "Only the first sample is scored — this is pass@1 with one attempt, "
            "not the pass@k of the original paper.",
        ),
        scoring_note=(
            "A Python scorer extracts the code block, defines the function and "
            "runs the benchmark's `check()` against it. Free of API cost, and "
            "the only benchmark here that runs the model's output as a program."
        ),
        bundled_sample_path="humaneval.jsonl",
        method=Method(
            fidelity=OFFICIAL,
            comparable=True,
            deviations=(
                "pass@1 from a single sample. The paper estimates pass@k from n "
                "samples per problem, and a one-sample pass@1 is noisier than an "
                "estimated one — especially at temperature above zero.",
                "The official harness runs candidates in a restricted subprocess "
                "with resource limits. Gaugix executes them in-process with no "
                "sandbox at all, which is a safety difference, not a scoring one.",
            ),
        ),
        source=Source(
            url=(
                "https://raw.githubusercontent.com/openai/human-eval/"
                "463c980b59e818ace59f6f9803cd92c749ceae61/data/HumanEval.jsonl.gz"
            ),
            encoding=HTTP_JSONL_GZ,
            approx_bytes=44_877,
            host="raw.githubusercontent.com",
            revision="463c980b59e818ace59f6f9803cd92c749ceae61",
            sha256="b796127e635a67f93fb35c04f4cb03cf06f38c8072ee7cee8833d7bee06979ef",
            expected_rows=164,
        ),
        requires_code_execution=True,
        tags=("code", "deterministic", "executes-output"),
    ),
)

BY_SLUG = {entry.slug: entry for entry in CATALOG}


def get(slug: str) -> Benchmark | None:
    return BY_SLUG.get(slug)


@dataclass(slots=True)
class InstallPlan:
    """What an install is about to do, before it does any of it."""

    benchmark: Benchmark
    scope: str
    case_count: int
    set_name: str
    warnings: list[str] = field(default_factory=list)
