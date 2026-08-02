"""Foreign format adapters (`gaugix.formats`).

The properties worth testing are the honesty ones: a guess that cannot be made
becomes an error naming the columns, a translation that loses a check becomes a
warning naming the case, and nothing quietly evaluates the wrong field.
"""

from __future__ import annotations

import json

from gaugix.domain import Role, ScorerType
from gaugix.formats import (
    dump_csv,
    dump_openai_evals,
    parse_csv,
    parse_huggingface,
    parse_openai_evals,
    parse_promptfoo,
)
from gaugix.schemas.cases import FieldMapping

# -- csv -----------------------------------------------------------------------


def test_csv_guesses_the_obvious_columns():
    content = "question,answer\nWhat is 2+2?,4\nCapital of France?,Paris\n"

    cases, errors = parse_csv(content)

    assert errors == []
    assert [c.input[0].content for c in cases] == ["What is 2+2?", "Capital of France?"]
    assert [c.reference for c in cases] == ["4", "Paris"]


def test_csv_refuses_to_guess_when_nothing_looks_like_a_prompt():
    """Evaluating the wrong column silently is the failure mode to prevent."""
    content = "col_a,col_b\nfoo,bar\n"

    cases, errors = parse_csv(content)

    assert cases == []
    assert len(errors) == 1
    assert "mapping.input" in errors[0].message
    # It names what it did find, so the fix is one field away.
    assert "col_a" in errors[0].message and "col_b" in errors[0].message


def test_an_explicit_mapping_is_never_overridden_by_the_guess():
    """`question` would win the heuristic; the caller said `col_b`."""
    content = "question,col_b\nguessed,chosen\n"

    cases, _ = parse_csv(content, FieldMapping(input="col_b"))

    assert cases[0].input[0].content == "chosen"


def test_csv_reports_the_row_number_of_an_empty_prompt():
    content = "question,answer\nfine,1\n,2\n"

    cases, errors = parse_csv(content)

    assert len(cases) == 1
    # Header is line 1, so the blank row is line 3.
    assert errors[0].line == 3


def test_csv_sniffs_a_tab_separated_file():
    cases, errors = parse_csv("question\tanswer\nWhat is 2+2?\t4\n")

    assert errors == []
    assert cases[0].reference == "4"


def test_csv_picks_up_a_system_column_as_a_system_turn():
    cases, _ = parse_csv("system,question\nBe terse.,Why?\n")

    assert [m.role for m in cases[0].input] == [Role.system, Role.user]
    assert cases[0].input[0].content == "Be terse."


# -- openai/evals --------------------------------------------------------------


def test_openai_evals_reads_the_chat_shape():
    content = json.dumps({"input": [{"role": "user", "content": "2+2?"}], "ideal": "4"}) + "\n"

    cases, errors = parse_openai_evals(content)

    assert errors == []
    assert cases[0].input[0].content == "2+2?"
    assert cases[0].reference == "4"


def test_openai_evals_keeps_every_accepted_answer():
    """`ideal` is often a list. Keeping only the first would narrow correctness."""
    content = json.dumps({"input": "Capital?", "ideal": ["Paris", "paris", "PARIS"]})

    cases, _ = parse_openai_evals(content)

    assert cases[0].reference == "Paris"
    assert "paris" in (cases[0].notes or "") and "PARIS" in (cases[0].notes or "")


def test_openai_evals_reports_the_line_of_a_bad_row():
    content = '{"input": "ok", "ideal": "1"}\nnot json\n'

    cases, errors = parse_openai_evals(content)

    assert len(cases) == 1
    assert errors[0].line == 2


def test_openai_evals_round_trips_through_its_own_exporter():
    original = '{"input": [{"role": "user", "content": "2+2?"}], "ideal": "4"}\n'
    cases, _ = parse_openai_evals(original)

    again, errors = parse_openai_evals(dump_openai_evals(cases))

    assert errors == []
    assert again[0].input == cases[0].input
    assert again[0].reference == cases[0].reference


# -- huggingface ---------------------------------------------------------------


def test_huggingface_unwraps_the_datasets_server_envelope():
    payload = {
        "features": [{"name": "question"}, {"name": "answer"}],
        "rows": [
            {"row_idx": 0, "row": {"question": "2+2?", "answer": "4"}},
            {"row_idx": 1, "row": {"question": "3+3?", "answer": "6"}},
        ],
    }

    cases, errors = parse_huggingface(json.dumps(payload))

    assert errors == []
    assert [c.reference for c in cases] == ["4", "6"]


def test_huggingface_accepts_a_bare_list_of_rows():
    cases, errors = parse_huggingface(json.dumps([{"prompt": "hi", "answer": "hello"}]))

    assert errors == []
    assert cases[0].input[0].content == "hi"


def test_a_nested_column_becomes_json_not_a_python_repr():
    """`str(dict)` in a prompt is a bug that only shows up at inference time."""
    payload = [{"question": "pick one", "choices": {"a": 1}, "answer": "a"}]

    cases, _ = parse_huggingface(json.dumps(payload), FieldMapping(input="choices"))

    assert cases[0].input[0].content == '{"a": 1}'


# -- promptfoo -----------------------------------------------------------------

PROMPTFOO_CONFIG = """
prompts:
  - "Answer concisely: {{question}}"
tests:
  - description: arithmetic
    vars:
      question: "What is 2+2?"
    assert:
      - type: contains
        value: "4"
      - type: not-contains
        value: "sorry"
  - description: exactness
    vars:
      question: "Say OK"
    assert:
      - type: equals
        value: "OK"
"""


def test_promptfoo_renders_the_template_and_translates_assertions():
    cases, errors, warnings = parse_promptfoo(PROMPTFOO_CONFIG)

    assert errors == [] and warnings == []
    assert cases[0].title == "arithmetic"
    assert cases[0].input[0].content == "Answer concisely: What is 2+2?"
    assert [s.type for s in cases[0].scoring] == [ScorerType.contains, ScorerType.not_contains]


def test_promptfoo_equals_becomes_an_anchored_regex_not_a_contains():
    """`contains` would pass on "OK, here you go" — which `equals` must not."""
    cases, _, _ = parse_promptfoo(PROMPTFOO_CONFIG)

    scorer = cases[1].scoring[0]
    assert scorer.type == ScorerType.regex
    assert scorer.params["pattern"] == r"^\s*OK\s*$"
    assert scorer.params["should_match"] is True


def test_an_untranslatable_assertion_warns_instead_of_vanishing():
    """A case that silently loses a check looks scored and is not."""
    config = """
tests:
  - description: scripted
    vars:
      input: "hello"
    assert:
      - type: javascript
        value: "output.length > 3"
      - type: contains
        value: "hell"
"""
    cases, errors, warnings = parse_promptfoo(config)

    assert errors == []
    assert len(cases) == 1
    # The translatable half survives...
    assert [s.type for s in cases[0].scoring] == [ScorerType.contains]
    # ...and the other half is named, with the case it belonged to.
    assert len(warnings) == 1
    assert "javascript" in warnings[0].message
    assert "scripted" in warnings[0].message


def test_promptfoo_applies_default_test_assertions_to_every_case():
    config = """
defaultTest:
  assert:
    - type: not-contains
      value: "as an AI"
tests:
  - vars: {input: "one"}
  - vars: {input: "two"}
"""
    cases, errors, _ = parse_promptfoo(config)

    assert errors == []
    assert all(s.type == ScorerType.not_contains for c in cases for s in c.scoring)
    assert len(cases) == 2


def test_promptfoo_llm_rubric_becomes_a_judge_scorer_carrying_the_rubric():
    config = """
tests:
  - vars: {input: "explain recursion"}
    assert:
      - type: llm-rubric
        value: "Mentions a base case."
"""
    cases, _, _ = parse_promptfoo(config)

    scorer = cases[0].scoring[0]
    assert scorer.type == ScorerType.llm_judge
    assert scorer.params["rubric"] == "Mentions a base case."


def test_a_config_with_no_tests_says_so():
    cases, errors, _ = parse_promptfoo("prompts:\n  - hello\n")

    assert cases == []
    assert "tests" in errors[0].message


# -- export --------------------------------------------------------------------


def test_csv_export_flattens_to_the_last_user_turn():
    cases, _ = parse_csv("system,question,answer\nBe terse.,Why?,Because\n")

    table = dump_csv(cases)

    assert table.splitlines()[0] == "title,input,reference,tags,notes"
    # The system turn has nowhere to go in a flat table and is dropped rather
    # than smuggled into the prompt cell.
    assert "Why?" in table.splitlines()[1]
    assert "Be terse." not in table


def test_promptfoo_runs_every_test_against_every_prompt():
    """promptfoo evaluates prompts × tests; reading only the first dropped most of it."""
    config = """
prompts:
  - "Answer plainly: {{q}}"
  - "Answer as a pirate: {{q}}"
tests:
  - description: Capital
    vars:
      q: capital of France?
    assert:
      - type: contains
        value: Paris
  - description: Colour
    vars:
      q: colour of the sky?
"""

    cases, errors, warnings = parse_promptfoo(config)

    assert errors == []
    assert len(cases) == 4, "two prompts × two tests"
    assert {c.title for c in cases} == {
        "Capital · prompt 1",
        "Colour · prompt 1",
        "Capital · prompt 2",
        "Colour · prompt 2",
    }
    assert "Answer as a pirate" in cases[2].input[0].content
    assert any("2 prompts" in w.message for w in warnings), "the fan-out must be stated"


def test_promptfoo_with_one_prompt_is_unchanged():
    config = """
prompts:
  - "Answer: {{q}}"
tests:
  - description: Only
    vars:
      q: hello?
"""

    cases, errors, warnings = parse_promptfoo(config)

    assert errors == []
    assert [c.title for c in cases] == ["Only"], "no suffix when there is nothing to disambiguate"
    assert warnings == []


def test_promptfoo_literal_prompts_are_imported_not_dropped():
    """A prompt needs no {{var}} to be a prompt; requiring one lost them all."""
    config = """
prompts:
  - First literal
  - Second literal
tests:
  - vars:
      input: hello
"""

    cases, errors, warnings = parse_promptfoo(config)

    assert errors == []
    assert [c.input[0].content for c in cases] == ["First literal", "Second literal"]
    assert any("2 prompts" in w.message for w in warnings)


def test_promptfoo_prompts_that_live_in_files_are_reported():
    """promptfoo resolves these at run time against files Gaugix never sees."""
    config = """
prompts:
  - file://prompts/system.txt
  - "Inline: {{q}}"
tests:
  - vars:
      q: hello?
"""

    cases, errors, warnings = parse_promptfoo(config)

    assert errors == []
    assert len(cases) == 1, "only the inline prompt is importable"
    assert any("outside this config" in w.message for w in warnings)
    assert any("file://prompts/system.txt" in w.message for w in warnings)
