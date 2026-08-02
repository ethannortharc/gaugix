"""Scorer programs shipped with catalogue benchmarks.

These are Python scorer sources — text, not imported code. They are written into
each installed case's scoring config, which means the user can read them in the
case editor, edit them, or delete them. That visibility is the point: Gaugix
runs Python scorers on the host without a sandbox (see
:mod:`gaugix.scoring.python_scorer`), so a scorer that arrives with a dataset
must be as inspectable as one you typed yourself.

Two of them matter:

* :data:`IFEVAL_VERIFIER` re-implements a documented subset of IFEval's
  programmatic instruction checks. Instructions outside the subset return
  `{"error": ...}`, which lands the item as *unscored* — never as a pass and
  never as a fail, because a check we did not run is not a check we failed.
* :data:`HUMANEVAL_RUNNER` executes the model's code against the benchmark's
  own unit tests. It runs untrusted model output on this machine, so the
  catalogue marks HumanEval `requires_code_execution` and the install refuses
  without an explicit acknowledgement.
"""

from __future__ import annotations

#: Final-answer match for GSM8K-style tasks: the reference is the gold number
#: and the model's *last* number must equal it. Written as a scorer rather than
#: a regex because "1,000" and "1000" are the same answer and a regex per case
#: cannot know that.
FINAL_NUMBER_MATCH = '''
import re


def score(case, output):
    """Compare the last number in the output against the reference."""
    reference = (case.get("reference") or "").strip()
    if not reference:
        return {"error": "this case has no reference answer to compare against"}

    def numbers(text):
        # Strip thousands separators so 1,000 and 1000 compare equal, and keep
        # a trailing decimal only when it carries information.
        cleaned = re.sub(r"(?<=\\d),(?=\\d{3}\\b)", "", text)
        return re.findall(r"-?\\d+(?:\\.\\d+)?", cleaned)

    gold = numbers(reference)
    guess = numbers(output)
    if not gold:
        return {"error": f"could not find a number in the reference {reference!r}"}
    if not guess:
        return {"passed": False, "rationale": "the answer contains no number"}

    want, got = gold[-1], guess[-1]
    same = abs(float(want) - float(got)) < 1e-6
    return {
        "passed": same,
        "rationale": f"final number {got} vs expected {want}",
    }
'''


#: Every instruction type in IFEval's official registry. Kept as data so the
#: installer can state coverage before a run rather than after, and so a future
#: dataset revision that adds a type fails loudly here instead of silently
#: producing unscored items.
IFEVAL_INSTRUCTIONS: tuple[str, ...] = (
    "keywords:existence",
    "keywords:frequency",
    "keywords:forbidden_words",
    "keywords:letter_frequency",
    "language:response_language",
    "length_constraints:number_sentences",
    "length_constraints:number_paragraphs",
    "length_constraints:number_words",
    "length_constraints:nth_paragraph_first_word",
    "detectable_content:number_placeholders",
    "detectable_content:postscript",
    "detectable_format:number_bullet_lists",
    "detectable_format:constrained_response",
    "detectable_format:number_highlighted_sections",
    "detectable_format:multiple_sections",
    "detectable_format:json_format",
    "detectable_format:title",
    "combination:two_responses",
    "combination:repeat_prompt",
    "startend:end_checker",
    "change_case:capital_word_frequency",
    "change_case:english_capital",
    "change_case:english_lowercase",
    "punctuation:no_comma",
    "startend:quotation",
)

#: The two rules whose official implementation Gaugix cannot reproduce exactly,
#: and what it does instead. Surfaced in the catalogue, not buried here.
IFEVAL_APPROXIMATIONS: tuple[tuple[str, str], ...] = (
    (
        "language:response_language",
        "the official checker uses langdetect; Gaugix identifies the script and, "
        "for languages sharing one, a function-word profile. It declines to "
        "judge rather than guess when the evidence is thin.",
    ),
    (
        "length_constraints:number_sentences",
        "the official checker tokenises sentences with NLTK's Punkt model; "
        "Gaugix splits on sentence-final punctuation, which differs on "
        "abbreviations such as “Dr.”.",
    ),
)


#: IFEval's instruction verifiers, following the official implementation rule by
#: rule. Where Gaugix cannot reproduce a rule exactly it says so in
#: :data:`IFEVAL_APPROXIMATIONS`; where it cannot verify at all the case comes
#: back **unscored**, never as a pass and never as a fail.
IFEVAL_VERIFIER = '''
import json
import re

#: IFEval's comparisons are strict on one side: "less than" is `<`, not `<=`.
#: Reading it as `<=` turns every boundary case into a false pass.
_LESS_THAN = "less than"


def _count_words(text):
    """Official IFEval counts `\\\\w+` tokens, so "don't" is two words."""
    return len(re.findall(r"\\w+", text))


def _count_sentences(text):
    """Approximates NLTK Punkt: split on sentence-final punctuation."""
    return len([s for s in re.split(r"(?<=[.!?])\\s+", text.strip()) if s.strip()])


def _compare(found, want, relation):
    return found < want if relation == _LESS_THAN else found >= want


def _tokenise(text):
    """Words, keeping hyphens and apostrophes inside them.

    Approximates NLTK's tokeniser closely enough for the one rule that needs
    it: `ABC-DEF` is one word, not two.
    """
    return re.findall(r"[^\\W_]+(?:[-'][^\\W_]+)*", text)


# -- language identification ---------------------------------------------------

#: Scripts that identify exactly one of IFEval's languages.
_UNIQUE_SCRIPTS = (
    ("ja", "\\u3040-\\u30ff"),
    ("ko", "\\uac00-\\ud7af\\u1100-\\u11ff"),
    ("th", "\\u0e00-\\u0e7f"),
    ("he", "\\u0590-\\u05ff"),
    ("bn", "\\u0980-\\u09ff"),
    ("pa", "\\u0a00-\\u0a7f"),
    ("gu", "\\u0a80-\\u0aff"),
    ("ta", "\\u0b80-\\u0bff"),
    ("te", "\\u0c00-\\u0c7f"),
    ("kn", "\\u0c80-\\u0cff"),
    ("ml", "\\u0d00-\\u0d7f"),
)

#: Scripts several of IFEval's languages share, disambiguated by letters only
#: some of them use.
_SHARED_SCRIPTS = (
    ("\\u0900-\\u097f", ("hi", "mr", "ne")),
    ("\\u0400-\\u04ff", ("ru", "uk", "bg")),
    ("\\u0600-\\u06ff", ("ar", "fa", "ur")),
)

#: Letters and function words that separate languages sharing a script. Scored
#: by how many of a language's markers appear, relative to its rivals'.
_MARKERS = {
    "uk": ("\\u0456", "\\u0457", "\\u0454", "\\u0491"),
    "ru": ("\\u044b", "\\u044d", "\\u0451"),
    "bg": ("\\u0449", " \\u0432 ", " \\u043d\\u0430 ", " \\u0441\\u0430 "),
    "ur": ("\\u0679", "\\u0688", "\\u0691", "\\u06ba", "\\u06c1", "\\u06d2"),
    "fa": ("\\u067e", "\\u0686", "\\u0698", "\\u06af", "\\u06a9"),
    "ar": (" \\u0641\\u064a ", " \\u0639\\u0644\\u0649 ", " \\u0645\\u0646 "),
    "hi": (" \\u0939\\u0948 ", " \\u0915\\u093e ", " \\u0914\\u0930 "),
    "mr": ("\\u0933", " \\u0906\\u0939\\u0947 ", " \\u0906\\u0923\\u093f "),
    "ne": (" \\u091b ", " \\u0930 ", " \\u0917\\u0930\\u0947 "),
    "en": (" the ", " and ", " of ", " is ", " to ", " that "),
    "es": (" el ", " la ", " que ", " de ", " los ", " una ", "\\u00f1"),
    "pt": (" o ", " que ", " de ", " uma ", " n\\u00e3o ", "\\u00e3", "\\u00f5"),
    "fr": (" le ", " la ", " les ", " des ", " est ", " une ", "\\u00e7"),
    "de": (" der ", " die ", " und ", " das ", " nicht ", "\\u00df", "\\u00fc"),
    "it": (" il ", " che ", " di ", " non ", " una ", " gli "),
    "pl": (" nie ", " jest ", " si\\u0119 ", "\\u0142", "\\u017c", "\\u0107"),
    "fi": (" ja ", " on ", " ett\\u00e4 ", " ei ", "\\u00e4", "\\u00f6"),
    "vi": (" c\\u1ee7a ", " v\\u00e0 ", " l\\u00e0 ", "\\u01b0", "\\u1ea1"),
    "sw": (" na ", " ya ", " kwa ", " ni ", " katika "),
}

_LATIN = ("en", "es", "pt", "fr", "de", "it", "pl", "fi", "vi", "sw")


def _script_of(text):
    """(language or None, candidates) for the text's dominant script."""
    for code, ranges in _UNIQUE_SCRIPTS:
        if re.search("[" + ranges + "]", text):
            return code, (code,)
    for ranges, candidates in _SHARED_SCRIPTS:
        if re.search("[" + ranges + "]", text):
            return None, candidates
    if re.search(r"[A-Za-z]", text):
        return None, _LATIN
    return None, ()


def _marker_score(code, padded):
    return sum(padded.count(marker) for marker in _MARKERS.get(code, ()))


def _detect_language(text, candidates):
    """The best-supported candidate, or None when nothing wins clearly."""
    padded = " " + re.sub(r"\\s+", " ", text.lower()) + " "
    scored = sorted(((_marker_score(c, padded), c) for c in candidates), reverse=True)
    if not scored or scored[0][0] == 0:
        return None
    if len(scored) > 1 and scored[1][0] * 2 > scored[0][0]:
        return None
    return scored[0][1]


def _looks_english(text):
    """True unless the text is confidently some other language.

    The official checkers pair their case rules with langdetect and count a
    detection failure as compliance. This keeps that shape: only a confident
    identification of a *different* language fails the rule.
    """
    passed, _ = _check_language("en", text)
    return passed is not False


def _check_language(want, output):
    unique, candidates = _script_of(output)
    if not candidates:
        return (None, "the answer has no letters to identify a language from")
    if want not in candidates:
        found = unique or "/".join(candidates)
        return (False, f"written in {found}, wanted {want}")
    if unique is not None:
        return (True, f"written in {want}")
    detected = _detect_language(output, candidates)
    if detected is None:
        return (None, f"cannot tell {' or '.join(candidates)} apart in this answer")
    return (detected == want, f"reads as {detected}, wanted {want}")


# -- the instruction registry --------------------------------------------------


def _check(instruction, kwargs, output):
    """Return (passed, detail), or (None, why) when this rule cannot be run."""
    k = kwargs or {}

    if instruction == "punctuation:no_comma":
        return ("," not in output, "found a comma" if "," in output else "no commas")

    if instruction == "change_case:english_lowercase":
        # Official checks the case *and* that the text is English, so "bonjour
        # tout le monde" fails. It counts an undetectable language as following,
        # which is what `_looks_english` returns when it cannot tell.
        return (
            output.islower() and _looks_english(output),
            "must be all lowercase, in English",
        )

    if instruction == "change_case:english_capital":
        return (
            output.isupper() and _looks_english(output),
            "must be all uppercase, in English",
        )

    if instruction == "change_case:capital_word_frequency":
        # Hyphenated words are one word: official tokenises with NLTK, where
        # ABC-DEF is a single token. A `\\b[A-Z]+\\b` scan counted it as two and
        # passed "at least 2 capitals" on one word.
        found = len([w for w in _tokenise(output) if w.isupper()])
        want = int(k.get("capital_frequency", 1))
        relation = str(k.get("capital_relation", "at least"))
        ok = _compare(found, want, relation)
        return (ok, f"{found} all-caps words, wanted {relation} {want}")

    if instruction == "detectable_format:number_highlighted_sections":
        single = [h for h in re.findall(r"\\*[^\\n\\*]*\\*", output) if h.strip("*").strip()]
        double = [
            h
            for h in re.findall(r"\\*\\*[^\\n\\*]*\\*\\*", output)
            if h.removeprefix("**").removesuffix("**").strip()
        ]
        found = len(single) + len(double)
        want = int(k.get("num_highlights", 1))
        return (found >= want, f"{found} highlighted sections, wanted {want}")

    if instruction == "detectable_format:number_bullet_lists":
        found = len(re.findall(r"^\\s*\\*[^\\*].*$", output, re.M)) + len(
            re.findall(r"^\\s*-.*$", output, re.M)
        )
        want = int(k.get("num_bullets", 1))
        return (found == want, f"{found} bullets, wanted exactly {want}")

    if instruction == "detectable_format:constrained_response":
        options = ("My answer is yes.", "My answer is no.", "My answer is maybe.")
        hit = any(option in output.strip() for option in options)
        return (hit, "must answer with one of: " + ", ".join(options))

    if instruction == "detectable_format:multiple_sections":
        splitter = str(k.get("section_spliter", "Section"))
        parts = re.split(r"\\s?" + re.escape(splitter) + r"\\s?\\d+\\s?", output)
        found = len(parts) - 1
        want = int(k.get("num_sections", 1))
        return (found >= want, f"{found} sections, wanted {want}")

    if instruction == "detectable_format:json_format":
        body = output.strip()
        for fence in ("```json", "```Json", "```JSON", "```"):
            body = body.removeprefix(fence)
        body = body.removesuffix("```").strip()
        try:
            json.loads(body)
        except ValueError:
            return (False, "the answer is not valid JSON")
        return (True, "valid JSON")

    if instruction == "detectable_format:title":
        titles = [t for t in re.findall(r"<<[^\\n]+>>", output) if t.strip("<>").strip()]
        return (bool(titles), "needs a title wrapped in << >>")

    if instruction == "detectable_content:number_placeholders":
        found = len(re.findall(r"\\[.*?\\]", output))
        want = int(k.get("num_placeholders", 1))
        return (found >= want, f"{found} placeholders, wanted {want}")

    if instruction == "detectable_content:postscript":
        marker = str(k.get("postscript_marker", "P.S."))
        if marker == "P.P.S":
            pattern = r"\\s*p\\.\\s?p\\.\\s?s.*$"
        elif marker == "P.S.":
            pattern = r"\\s*p\\.\\s?s\\..*$"
        else:
            pattern = r"\\s*" + re.escape(marker.lower()) + r".*$"
        found = re.findall(pattern, output.lower(), re.M)
        return (bool(found), f"missing a {marker} postscript")

    if instruction == "startend:end_checker":
        end = str(k.get("end_phrase", "")).strip().lower()
        tail = output.strip().strip('"').lower()
        return (tail.endswith(end), f"must end with {end!r}")

    if instruction == "startend:quotation":
        stripped = output.strip()
        wrapped = len(stripped) > 1 and stripped[0] == '"' and stripped[-1] == '"'
        return (wrapped, "the whole answer must be wrapped in double quotes")

    if instruction == "keywords:existence":
        wanted = [str(w) for w in k.get("keywords", [])]
        missing = [w for w in wanted if not re.search(re.escape(w), output, re.I)]
        detail = f"missing: {', '.join(missing)}" if missing else "all present"
        return (not missing, detail)

    if instruction == "keywords:forbidden_words":
        banned = [str(w) for w in k.get("forbidden_words", [])]
        present = [w for w in banned if re.search(r"\\b" + re.escape(w) + r"\\b", output, re.I)]
        detail = f"used forbidden: {', '.join(present)}" if present else "none used"
        return (not present, detail)

    if instruction == "keywords:frequency":
        word = str(k.get("keyword", ""))
        want = int(k.get("frequency", 1))
        relation = str(k.get("relation", "at least"))
        found = len(re.findall(re.escape(word), output, re.I))
        detail = f"{word!r} appears {found}x, wanted {relation} {want}"
        return (_compare(found, want, relation), detail)

    if instruction == "keywords:letter_frequency":
        letter = str(k.get("letter", "")).lower()
        want = int(k.get("let_frequency", 1))
        relation = str(k.get("let_relation", "at least"))
        found = output.lower().count(letter) if letter else 0
        detail = f"{letter!r} appears {found}x, wanted {relation} {want}"
        return (_compare(found, want, relation), detail)

    if instruction == "language:response_language":
        return _check_language(str(k.get("language", "")).lower(), output)

    if instruction == "length_constraints:number_words":
        found = _count_words(output)
        want = int(k.get("num_words", 0))
        relation = str(k.get("relation", "at least"))
        return (_compare(found, want, relation), f"{found} words, wanted {relation} {want}")

    if instruction == "length_constraints:number_sentences":
        found = _count_sentences(output)
        want = int(k.get("num_sentences", 0))
        relation = str(k.get("relation", "at least"))
        return (_compare(found, want, relation), f"{found} sentences, wanted {relation} {want}")

    if instruction == "length_constraints:number_paragraphs":
        # IFEval's prompts ask for paragraphs separated by a `***` divider, so
        # that is what the official checker splits on — not blank lines.
        paragraphs = re.split(r"\\s?\\*\\*\\*\\s?", output)
        found = len(paragraphs)
        for index, paragraph in enumerate(paragraphs):
            if not paragraph.strip():
                if index in (0, len(paragraphs) - 1):
                    found -= 1
                else:
                    return (False, "an empty paragraph between two dividers")
        want = int(k.get("num_paragraphs", 0))
        return (found == want, f"{found} paragraphs, wanted exactly {want}")

    if instruction == "length_constraints:nth_paragraph_first_word":
        paragraphs = [p for p in re.split(r"\\n\\n", output)]
        live = [p for p in paragraphs if p.strip()]
        want_count = int(k.get("num_paragraphs", 0))
        nth = int(k.get("nth_paragraph", 1))
        wanted_word = str(k.get("first_word", "")).lower()
        if nth > len(live) or not live:
            return (False, f"only {len(live)} paragraphs, needed at least {nth}")
        word = live[nth - 1].strip().split()[0].lstrip("'").lstrip('"')
        first = ""
        for letter in word:
            if letter in {".", ",", "?", "!", "'", '"'}:
                break
            first += letter.lower()
        ok = len(live) == want_count and first == wanted_word
        return (ok, f"paragraph {nth} starts with {first!r}, wanted {wanted_word!r}")

    if instruction == "combination:repeat_prompt":
        prompt = str(k.get("prompt_to_repeat", "")).strip().lower()
        return (output.strip().lower().startswith(prompt), "must repeat the request verbatim first")

    if instruction == "combination:two_responses":
        parts = output.split("******")
        valid = []
        for index, part in enumerate(parts):
            if not part.strip():
                if index not in (0, len(parts) - 1):
                    return (False, "an empty response between two separators")
            else:
                valid.append(part)
        ok = len(valid) == 2 and valid[0].strip() != valid[1].strip()
        return (ok, f"{len(valid)} responses separated by ******, wanted 2 different ones")

    return (None, f"instruction {instruction!r} is not implemented by this scorer")


def score(case, output):
    """Every instruction on this case must hold. Unverifiable rules decline."""
    instructions = INSTRUCTIONS
    arguments = KWARGS

    results = []
    undecided = []
    for index, instruction in enumerate(instructions):
        kwargs = arguments[index] if index < len(arguments) else {}
        passed, detail = _check(instruction, kwargs, output)
        if passed is None:
            undecided.append(f"{instruction}: {detail}")
        else:
            results.append((instruction, passed, detail))

    # Anything unverified makes the whole verdict unsafe: a case whose only
    # failing rule is one we skipped would read as a pass.
    if undecided:
        return {"error": "; ".join(undecided)}
    if not results:
        return {"error": "this case carries no instructions to verify"}

    failed = [f"{name}: {detail}" for name, passed, detail in results if not passed]
    return {
        "passed": not failed,
        "value": round(100 * (len(results) - len(failed)) / len(results), 1),
        "rationale": "; ".join(failed) if failed else "every instruction satisfied",
    }
'''


#: Runs the model's code against HumanEval's own unit tests. This *executes
#: model output*; nothing here contains it.
HUMANEVAL_RUNNER = '''
import re


def _extract_code(text):
    """Prefer a fenced block; fall back to the whole answer."""
    fenced = re.findall(r"```(?:python)?\\n(.*?)```", text, re.S)
    return fenced[0] if fenced else text


def score(case, output):
    """Define the function, then run the benchmark's check() against it."""
    prompt = PROMPT
    test = TEST
    entry_point = ENTRY_POINT

    candidate = _extract_code(output)
    # Completion-style answers continue the signature rather than restating it,
    # so try the answer alone first and prepend the prompt only if it is needed.
    attempts = [candidate, prompt + candidate]

    last_error = None
    for source in attempts:
        namespace = {}
        try:
            exec(compile(source, "<humaneval-candidate>", "exec"), namespace)
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            continue
        if entry_point not in namespace:
            last_error = f"no function named {entry_point!r} was defined"
            continue

        try:
            exec(compile(test, "<humaneval-test>", "exec"), namespace)
            namespace["check"](namespace[entry_point])
        except AssertionError as exc:
            return {"passed": False, "rationale": f"a test assertion failed: {exc}"}
        except Exception as exc:
            return {"passed": False, "rationale": f"{type(exc).__name__}: {exc}"}
        return {"passed": True, "rationale": "every unit test passed"}

    return {"passed": False, "rationale": last_error or "the answer contained no runnable code"}
'''
