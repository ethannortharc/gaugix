"""The benchmark catalogue, its adapters, and the scorers they ship.

Everything here runs offline against the sample rows committed to the repo —
which is the point of bundling them. The shipped Python scorers are executed for
real (they are the substance of the feature, not decoration), so a broken
regular expression in `scorers.py` fails the suite rather than a user's run.
"""

from __future__ import annotations

import json

import pytest

from gaugix.benchmarks import CATALOG, Benchmark, get, load_cases
from gaugix.benchmarks.install import SAMPLE, decode_rows
from gaugix.domain import CaseSnapshot, ScorerType
from gaugix.scoring.python_scorer import score_python


def benchmark(slug: str) -> Benchmark:
    """`get` is nullable by design; in a test an unknown slug is a bug, not a branch."""
    entry = get(slug)
    assert entry is not None, f"no benchmark called {slug!r}"
    return entry


# -- catalogue integrity -------------------------------------------------------


def test_every_entry_has_a_bundled_sample_that_adapts_cleanly():
    """A catalogue row you cannot install offline is a broken promise."""
    for entry in CATALOG:
        cases = entry.sample_cases()
        assert cases, f"{entry.slug} produced no cases from its bundled rows"
        for case in cases:
            assert case.title.strip()
            assert case.input and case.input[0].content.strip()


def test_every_entry_states_reasons_to_distrust_it():
    """`caveats` is the field that stops this being a marketing page."""
    for entry in CATALOG:
        assert entry.caveats, f"{entry.slug} claims no caveats"
        assert entry.scoring_note.strip()
        assert entry.licence and entry.licence_url


def test_slugs_are_unique_and_every_one_has_an_adapter():
    slugs = [entry.slug for entry in CATALOG]
    assert len(slugs) == len(set(slugs))
    for entry in CATALOG:
        assert callable(entry.adapter)


def test_a_judge_or_code_execution_requirement_is_declared_not_implied():
    """The install dialog gates on these flags, so they must match the recipe."""
    for entry in CATALOG:
        types = {s.type for case in entry.sample_cases() for s in case.scoring}
        assert entry.requires_judge == (ScorerType.llm_judge in types), entry.slug
    assert benchmark("humaneval").requires_code_execution is True
    assert benchmark("gsm8k").requires_code_execution is False


# -- adapters ------------------------------------------------------------------


def test_gsm8k_takes_the_number_after_the_marker_as_the_reference():
    cases = benchmark("gsm8k").sample_cases()

    assert cases[0].reference == "18"
    # The worked solution is kept as context, never as the thing being matched.
    assert "####" not in (cases[0].reference or "")
    assert "Janet sells" in (cases[0].notes or "")


def test_mt_bench_keeps_the_second_turn_out_of_the_prompt():
    """Turn 2 depends on the model's own turn-1 answer; replaying it would be wrong."""
    cases = benchmark("mt-bench").sample_cases()

    first = cases[0]
    assert "Compose an engaging travel blog post" in first.input[0].content
    assert "Start every sentence with the letter A" not in first.input[0].content
    assert "Start every sentence with the letter A" in (first.notes or "")
    assert first.scoring[0].type == ScorerType.llm_judge


def test_ifeval_carries_its_constraints_into_the_scorer():
    cases = benchmark("ifeval").sample_cases()

    code = cases[0].scoring[0].params["code"]
    assert cases[0].scoring[0].type == ScorerType.python
    assert "punctuation:no_comma" in code
    assert "num_highlights" in code


def test_truthfulqa_puts_both_answer_sets_in_the_rubric():
    cases = benchmark("truthfulqa").sample_cases()

    rubric = cases[0].scoring[0].params["rubric"]
    assert "watermelon seeds pass through your digestive system" in rubric
    assert "You grow watermelons in your stomach" in rubric
    assert cases[0].reference == "The watermelon seeds pass through your digestive system"


def test_simpleqa_reads_the_topic_out_of_its_metadata_column():
    cases = benchmark("simpleqa").sample_cases()

    assert cases[0].reference == "Michio Sugeno"
    assert "science and technology" in cases[0].tags


def test_humaneval_ships_the_tests_with_the_case():
    cases = benchmark("humaneval").sample_cases()

    code = cases[0].scoring[0].params["code"]
    assert cases[0].title.startswith("HumanEval/0")
    assert "has_close_elements" in code
    assert "def check(candidate)" in code


def test_a_prompt_containing_a_constant_name_cannot_rewrite_the_scorer():
    """Constants are injected as bindings, not by substituting text in the source."""
    from gaugix.benchmarks.adapters import adapt_humaneval

    cases = adapt_humaneval(
        [
            {
                "task_id": "T/1",
                "prompt": "def f():\n    # PROMPT TEST ENTRY_POINT\n",
                "test": "def check(candidate):\n    assert candidate() == 1\n",
                "entry_point": "f",
            }
        ]
    )

    code = cases[0].scoring[0].params["code"]
    # The literal words survive inside the injected data, and the scorer's own
    # `prompt = PROMPT` line is still intact.
    assert "prompt = PROMPT" in code
    assert code.startswith("PROMPT = ")


# -- shipped scorers, actually executed ----------------------------------------


def _snapshot(case) -> CaseSnapshot:
    return CaseSnapshot(
        title=case.title,
        input=case.input,
        reference=case.reference,
        scoring=case.scoring,
        tags=case.tags,
        notes=case.notes,
    )


def _run(case, output: str):
    return score_python(case.scoring[0].params, _snapshot(case), output)


def test_the_gsm8k_scorer_matches_the_final_number():
    case = benchmark("gsm8k").sample_cases()[0]  # reference "18"

    assert _run(case, "She sells 9 eggs, so she makes $18 a day.").passed is True
    assert _run(case, "The answer is 16.").passed is False


def test_the_gsm8k_scorer_ignores_thousands_separators():
    """`1,000` and `1000` are the same answer; a per-case regex could not know."""
    from gaugix.benchmarks.adapters import adapt_gsm8k

    case = adapt_gsm8k([{"question": "how much?", "answer": "working\n#### 70000"}])[0]

    assert _run(case, "So he made a profit of $70,000.").passed is True


def test_the_gsm8k_scorer_declines_when_there_is_no_reference():
    from gaugix.benchmarks.adapters import adapt_gsm8k
    from gaugix.benchmarks.scorers import FINAL_NUMBER_MATCH

    case = adapt_gsm8k([{"question": "q", "answer": "w\n#### 5"}])[0]
    blank = _snapshot(case).model_copy(update={"reference": None})

    result = score_python({"code": FINAL_NUMBER_MATCH}, blank, "5")

    # Declining is unscored, not a fail — the item has no verdict at all.
    assert result.passed is None and result.error is True
    assert "no reference" in result.rationale


def test_the_ifeval_scorer_enforces_every_constraint():
    from gaugix.benchmarks.adapters import adapt_ifeval

    case = adapt_ifeval(
        [
            {
                "prompt": "write something",
                "instruction_id_list": ["punctuation:no_comma", "length_constraints:number_words"],
                "kwargs": [{}, {"relation": "at least", "num_words": 5}],
            }
        ]
    )[0]

    assert _run(case, "one two three four five six").passed is True
    # A comma alone fails it...
    assert _run(case, "one two, three four five six").passed is False
    # ...and so does being too short.
    result = _run(case, "too short")
    assert result.passed is False
    assert "number_words" in (result.rationale or "")


def test_the_ifeval_scorer_declines_rather_than_guess_at_an_unknown_rule():
    """An unverified constraint must not silently become a pass."""
    from gaugix.benchmarks.adapters import adapt_ifeval

    case = adapt_ifeval(
        [
            {
                "prompt": "p",
                "instruction_id_list": ["detectable_format:interpretive_dance"],
                "kwargs": [{}],
            }
        ]
    )[0]

    result = _run(case, "anything at all")

    assert result.passed is None and result.error is True
    assert "not implemented" in result.rationale


def test_every_official_ifeval_instruction_is_implemented():
    """Coverage is the score's credibility: a skipped rule is an unscored case."""
    from gaugix.benchmarks.adapters import adapt_ifeval
    from gaugix.benchmarks.scorers import IFEVAL_INSTRUCTIONS

    unimplemented = []
    for instruction in IFEVAL_INSTRUCTIONS:
        case = adapt_ifeval(
            [{"prompt": "p", "instruction_id_list": [instruction], "kwargs": [{}]}]
        )[0]
        if "not implemented" in (_run(case, "some answer").rationale or ""):
            unimplemented.append(instruction)

    assert unimplemented == []


def test_less_than_is_strict_so_the_boundary_fails():
    """`<=` where the paper says `<` turns every boundary case into a false pass."""
    from gaugix.benchmarks.adapters import adapt_ifeval

    case = adapt_ifeval(
        [
            {
                "prompt": "p",
                "instruction_id_list": ["length_constraints:number_words"],
                "kwargs": [{"relation": "less than", "num_words": 5}],
            }
        ]
    )[0]

    assert _run(case, "one two three four").passed is True
    assert _run(case, "one two three four five").passed is False, "exactly five is not fewer"


def test_ifeval_paragraphs_are_divided_by_the_marker_not_by_blank_lines():
    """IFEval's prompts ask for `***` dividers, and that is what it counts."""
    from gaugix.benchmarks.adapters import adapt_ifeval

    case = adapt_ifeval(
        [
            {
                "prompt": "p",
                "instruction_id_list": ["length_constraints:number_paragraphs"],
                "kwargs": [{"num_paragraphs": 2}],
            }
        ]
    )[0]

    assert _run(case, "first\n***\nsecond").passed is True
    assert _run(case, "first\n\nsecond").passed is False


def test_response_language_reads_the_script_and_declines_when_unsure():
    from gaugix.benchmarks.adapters import adapt_ifeval

    def case_for(language):
        return adapt_ifeval(
            [
                {
                    "prompt": "p",
                    "instruction_id_list": ["language:response_language"],
                    "kwargs": [{"language": language}],
                }
            ]
        )[0]

    # A script that identifies one language answers outright, either way.
    assert _run(case_for("ja"), "これは日本語の文章です。").passed is True
    assert _run(case_for("ja"), "This is plainly English.").passed is False
    # Languages sharing the Latin script are told apart by function words.
    assert _run(case_for("fr"), "Le chat est sur la table et les enfants sont des amis.").passed
    # And when there is nothing to go on, it declines rather than guesses.
    assert _run(case_for("fr"), "42").passed is None


@pytest.mark.parametrize(
    ("instruction", "kwargs", "good", "bad"),
    [
        ("change_case:english_lowercase", {}, "all lower", "Has Caps"),
        ("detectable_content:number_placeholders", {"num_placeholders": 2}, "[a] [b]", "[a]"),
        ("startend:quotation", {}, '"quoted"', "unquoted"),
        ("keywords:forbidden_words", {"forbidden_words": ["banana"]}, "an apple", "a banana"),
        ("detectable_format:number_bullet_lists", {"num_bullets": 2}, "- a\n- b", "- a"),
    ],
)
def test_ifeval_rules_hold_in_both_directions(instruction, kwargs, good, bad):
    from gaugix.benchmarks.adapters import adapt_ifeval

    case = adapt_ifeval(
        [{"prompt": "p", "instruction_id_list": [instruction], "kwargs": [kwargs]}]
    )[0]

    assert _run(case, good).passed is True, f"{instruction} rejected a valid answer"
    assert _run(case, bad).passed is False, f"{instruction} accepted an invalid answer"


def test_the_humaneval_scorer_runs_the_benchmarks_own_tests():
    case = benchmark("humaneval").sample_cases()[0]
    solution = (
        "```python\n"
        "from typing import List\n"
        "def has_close_elements(numbers: List[float], threshold: float) -> bool:\n"
        "    for i, a in enumerate(numbers):\n"
        "        for j, b in enumerate(numbers):\n"
        "            if i != j and abs(a - b) < threshold:\n"
        "                return True\n"
        "    return False\n"
        "```"
    )

    assert _run(case, solution).passed is True


def test_the_humaneval_scorer_fails_a_wrong_implementation():
    case = benchmark("humaneval").sample_cases()[0]
    wrong = (
        "```python\n"
        "from typing import List\n"
        "def has_close_elements(numbers: List[float], threshold: float) -> bool:\n"
        "    return True\n"
        "```"
    )

    result = _run(case, wrong)

    assert result.passed is False
    assert "assertion" in (result.rationale or "").lower()


def test_the_humaneval_scorer_survives_an_answer_that_is_not_code():
    case = benchmark("humaneval").sample_cases()[0]

    result = _run(case, "I'm sorry, I can't help with that.")

    assert result.passed is False


# -- install planning ----------------------------------------------------------


def test_loading_the_sample_scope_never_needs_the_network(monkeypatch):
    """Belt and braces: fail loudly if a sample install ever grows an HTTP call."""
    import httpx

    def explode(*args, **kwargs):
        raise AssertionError("a sample install must not open a connection")

    monkeypatch.setattr(httpx.Client, "get", explode)

    for entry in CATALOG:
        assert load_cases(entry, SAMPLE)


def test_load_cases_can_cap_how_much_it_takes():
    assert len(load_cases(benchmark("gsm8k"), SAMPLE, limit=2)) == 2


def test_decode_rows_understands_gzipped_jsonl():
    import gzip

    body = gzip.compress(json.dumps({"a": 1}).encode() + b"\n")

    assert decode_rows(body, "jsonl.gz") == [{"a": 1}]


def test_decode_rows_reads_csv_into_dicts():
    assert decode_rows(b"a,b\n1,2\n", "csv") == [{"a": "1", "b": "2"}]


def test_a_seeded_sample_is_reproducible_and_not_just_the_head_of_the_file():
    """A benchmark's file order is rarely arbitrary, so the first N is not a sample."""
    from gaugix.benchmarks.install import take

    rows = [{"n": i} for i in range(100)]

    head = take(rows, 10, None)
    drawn = take(rows, 10, seed=7)
    again = take(rows, 10, seed=7)
    other = take(rows, 10, seed=8)

    assert head == rows[:10]
    assert drawn == again, "the same seed must draw the same cases"
    assert drawn != head
    assert drawn != other
    assert len(drawn) == 10


def test_taking_more_than_there_is_returns_everything():
    from gaugix.benchmarks.install import take

    rows = [{"n": i} for i in range(3)]

    assert take(rows, 10, seed=1) == rows
    assert take(rows, None, None) == rows


def test_a_download_that_does_not_match_the_catalogue_warns_rather_than_pretends():
    """This is exactly how TruthfulQA came to be described as 817 while shipping 790."""
    from gaugix.benchmarks.catalog import Source
    from gaugix.benchmarks.install import _drift

    source = Source(
        url="https://example.invalid/data.jsonl",
        encoding="jsonl",
        approx_bytes=10,
        host="example.invalid",
        sha256="a" * 64,
        expected_rows=100,
    )

    problems = _drift(source, "b" * 64, [{"n": i} for i in range(90)])

    assert len(problems) == 2
    assert "checksum" in problems[0]
    assert "90 rows, not the 100" in problems[1]


def test_a_matching_download_reports_no_drift():
    from gaugix.benchmarks.catalog import Source
    from gaugix.benchmarks.install import _drift

    source = Source(
        url="https://example.invalid/data.jsonl",
        encoding="jsonl",
        approx_bytes=10,
        host="example.invalid",
        sha256="c" * 64,
        expected_rows=2,
    )

    assert _drift(source, "c" * 64, [{"n": 1}, {"n": 2}]) == []


# -- provenance for sets installed before it was recorded ----------------------


def _legacy_set(session, name="HumanEval (old install)", tags=("benchmark:humaneval", "official")):
    from gaugix.models.cases import EvalSet

    eval_set = EvalSet(name=name)
    eval_set.tags = list(tags)
    eval_set.provenance = {}
    session.add(eval_set)
    session.commit()
    session.refresh(eval_set)
    return eval_set


def test_a_pre_provenance_benchmark_set_still_names_its_benchmark(session):
    from gaugix.benchmarks import effective_provenance

    record = effective_provenance(session, _legacy_set(session))

    assert record["benchmark"] == "humaneval"
    assert record["benchmark_name"] == "HumanEval"
    assert record["legacy"] is True
    # Not an adaptation and not a verified install — the method is unknown, and
    # the card rendered "Gaugix adaptation · unrecorded vunrecorded" instead.
    assert record["method_fidelity"] == "unrecorded"
    assert "comparable_to_published" not in record


def test_a_hand_made_set_has_no_provenance_to_infer(session):
    from gaugix.benchmarks import effective_provenance

    hand = _legacy_set(session, name="My own cases", tags=("custom",))
    assert effective_provenance(session, hand) == {}


def test_a_real_install_record_overrides_every_inferred_field(session):
    from gaugix.benchmarks import effective_provenance

    eval_set = _legacy_set(session, name="HumanEval (fresh)")
    eval_set.provenance = {
        "benchmark": "humaneval",
        "benchmark_name": "HumanEval",
        "method_fidelity": "official",
        "method_version": "3",
        "comparable_to_published": True,
    }
    session.add(eval_set)
    session.commit()

    record = effective_provenance(session, eval_set)
    assert record["method_fidelity"] == "official"
    assert record["method_version"] == "3"
    assert "legacy" not in record


def test_a_run_over_a_legacy_set_freezes_a_dataset_record(session):
    """The API inferred the record on read; the planner froze the raw column.

    So a run built on a pre-provenance set produced a report with no dataset
    section at all — a number with no statement of what it measured (D-066).
    """
    from gaugix.engine.planner import _provenance

    frozen = _provenance(session, _legacy_set(session))

    assert frozen["provenance"]["benchmark"] == "humaneval"
    assert frozen["provenance"]["legacy"] is True
    assert _provenance(session, _legacy_set(session, "Hand", ("custom",))) == {}


def test_english_case_rules_also_check_the_language():
    """Official pairs `islower()` with langdetect; case alone passed French."""
    from gaugix.benchmarks.adapters import adapt_ifeval

    def case_for(instruction):
        return adapt_ifeval(
            [{"prompt": "p", "instruction_id_list": [instruction], "kwargs": [{}]}]
        )[0]

    lower = case_for("change_case:english_lowercase")
    assert _run(lower, "the cat is on the table and it is fine").passed is True
    assert _run(lower, "bonjour tout le monde").passed is False
    # Too little to identify: official counts a detection failure as compliance.
    assert _run(lower, "hmm yes").passed is True

    upper = case_for("change_case:english_capital")
    assert _run(upper, "BONJOUR TOUT LE MONDE ET LES AMIS").passed is False


def test_hyphenated_words_count_once_in_the_capital_word_rule():
    """NLTK keeps ABC-DEF as one token; a word-boundary scan counted two."""
    from gaugix.benchmarks.adapters import adapt_ifeval

    case = adapt_ifeval(
        [
            {
                "prompt": "p",
                "instruction_id_list": ["change_case:capital_word_frequency"],
                "kwargs": [{"capital_frequency": 2, "capital_relation": "at least"}],
            }
        ]
    )[0]

    assert _run(case, "ABC-DEF").passed is False, "one hyphenated word is one word"
    assert _run(case, "ABC DEF").passed is True


def test_ifeval_does_not_claim_to_be_quotable():
    """Three rules approximate NLP components Gaugix cannot ship offline."""
    entry = benchmark("ifeval")

    assert entry.method.comparable is False
    assert entry.method.fidelity == "gaugix-adaptation"
    assert any("Not comparable" in d for d in entry.method.deviations)


def test_simpleqa_declares_its_three_classes_so_they_can_be_counted():
    """The split between wrong and declined is what SimpleQA exists to show."""
    spec = benchmark("simpleqa").sample_cases()[0].scoring[0]

    assert spec.params["classes"] == ["CORRECT", "INCORRECT", "NOT_ATTEMPTED"]


def test_a_declared_class_is_read_from_the_verdict():
    from gaugix.scoring.judge import classify

    classes = ("CORRECT", "INCORRECT", "NOT_ATTEMPTED")

    # The JSON field wins when present.
    assert classify("not_attempted", "whatever", classes) == "NOT_ATTEMPTED"
    # Otherwise it is read off the front of the rationale, where the rubric asks.
    assert classify(None, "NOT_ATTEMPTED — the model declined.", classes) == "NOT_ATTEMPTED"
    assert classify(None, "CORRECT, it names the right person.", classes) == "CORRECT"
    # A scale-graded rubric declares no classes and gets none.
    assert classify(None, "CORRECT", ()) is None
    assert classify(None, "the answer was fine", classes) is None


def test_a_redirect_off_the_declared_host_is_refused():
    """The page promises one host; follow_redirects quietly made that untrue."""
    import httpx
    import pytest

    from gaugix.benchmarks.install import _get_within_host
    from gaugix.errors import ValidationError

    def elsewhere(self, url, **kwargs):
        return httpx.Response(
            302,
            headers={"location": "https://evil.invalid/data.jsonl"},
            request=httpx.Request("GET", url),
        )

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(httpx.Client, "get", elsewhere)
        with pytest.raises(ValidationError) as raised:
            _get_within_host("https://example.invalid/data.jsonl", "example.invalid")

    assert "evil.invalid" in str(raised.value.message)


def test_a_same_host_redirect_is_followed():
    """Blob stores redirect to sign a URL; that is not a different host."""
    import httpx
    import pytest

    from gaugix.benchmarks.install import _get_within_host

    seen: list[str] = []

    def hop(self, url, **kwargs):
        seen.append(str(url))
        request = httpx.Request("GET", url)
        if len(seen) == 1:
            return httpx.Response(302, headers={"location": "/signed/data.jsonl"}, request=request)
        return httpx.Response(200, content=b"ok", request=request)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(httpx.Client, "get", hop)
        body = _get_within_host("https://example.invalid/data.jsonl", "example.invalid")

    assert body == b"ok"
    assert len(seen) == 2


# -- judge scale and class verdicts (D-060) ------------------------------------


def test_a_zero_to_one_scale_normalises_onto_the_same_axis_as_everything_else():
    """A correct SimpleQA answer scored 1.0 out of 100 everywhere it was shown."""
    from gaugix.scoring.aggregate import normalize_value

    assert normalize_value(1, "0-1") == 100.0
    assert normalize_value(0, "0-1") == 0.0
    assert normalize_value(0.5, "0-1") == 50.0
    # Binary stays a decision rather than becoming a fraction.
    assert normalize_value(0.5, "binary") == 0.0
    assert normalize_value(1, "binary") == 100.0


def test_the_judged_benchmarks_use_a_scale_the_normaliser_knows():
    for slug in ("simpleqa", "truthfulqa", "mt-bench"):
        for case in benchmark(slug).sample_cases():
            for spec in case.scoring:
                scale = spec.params.get("scale")
                assert scale in {"binary", "0-1", "1-5", "1-10", "0-100"}, (slug, scale)


def test_the_declared_class_decides_the_verdict_not_the_judges_pass_flag():
    """The page promises "Gaugix passes only CORRECT"; the flag could override it."""
    from gaugix.scoring.judge import _finalise

    classes = ("CORRECT", "INCORRECT", "NOT_ATTEMPTED")

    contradictory = _finalise(
        score=1,
        judge_pass=True,
        rationale="INCORRECT — it names the wrong person.",
        scale="binary",
        threshold=None,
        classification="INCORRECT",
        passing_classes=("CORRECT",),
        classes=classes,
    )

    assert contradictory.passed is False, "the class wins"
    assert contradictory.meta["contradiction"]["judge_pass"] is True
    assert "classified INCORRECT" in contradictory.rationale


def test_a_passing_class_passes():
    from gaugix.scoring.judge import _finalise

    result = _finalise(
        score=1,
        judge_pass=True,
        rationale="CORRECT — it names the right person.",
        scale="binary",
        threshold=None,
        classification="CORRECT",
        passing_classes=("CORRECT",),
        classes=("CORRECT", "INCORRECT", "NOT_ATTEMPTED"),
    )

    assert result.passed is True
    assert result.value == 100.0
    assert "contradiction" not in result.meta


def test_an_unclassifiable_reply_is_unscored_and_still_counted():
    """Dropping it would leave fewer classified items than items, invisibly."""
    from gaugix.scoring.judge import UNCLASSIFIED, _finalise

    result = _finalise(
        score=1,
        judge_pass=True,
        rationale="It seems fine to me.",
        scale="binary",
        threshold=None,
        classification=None,
        passing_classes=("CORRECT",),
        classes=("CORRECT", "INCORRECT", "NOT_ATTEMPTED"),
    )

    assert result.passed is None and result.error is True
    assert result.meta["classification"] == UNCLASSIFIED
