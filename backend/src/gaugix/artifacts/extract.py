"""Pulling files out of a model's prose (PRD F6.1).

Models answer a coding question with a fenced block inside an explanation. The
block *is* the deliverable, so it becomes a file you can open, diff and run —
not a region of a transcript you have to select by hand.

Two rules keep this honest:

* **Never guess an extension.** An unlabelled fence gets `.txt`. Naming a file
  `.py` because it happens to contain a colon would be a lie that only shows up
  when someone runs it.
* **Never rewrite the content.** What the model wrote is what gets stored, byte
  for byte, including trailing whitespace and a missing final newline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: ```lang\n…\n``` — tolerant of ~~~ fences, extra info after the language, and
#: a final fence that the model forgot to close.
FENCE = re.compile(
    r"^(?P<fence>```+|~~~+)[ \t]*(?P<info>[^\n]*)\n(?P<body>.*?)(?:^(?P=fence)[ \t]*$|\Z)",
    re.MULTILINE | re.DOTALL,
)

#: Fence language → (extension, mime). Only languages we are sure about.
LANGUAGES: dict[str, tuple[str, str]] = {
    "python": (".py", "text/x-python"),
    "py": (".py", "text/x-python"),
    "go": (".go", "text/x-go"),
    "golang": (".go", "text/x-go"),
    "rust": (".rs", "text/x-rust"),
    "rs": (".rs", "text/x-rust"),
    "javascript": (".js", "text/javascript"),
    "js": (".js", "text/javascript"),
    "typescript": (".ts", "text/typescript"),
    "ts": (".ts", "text/typescript"),
    "tsx": (".tsx", "text/typescript"),
    "jsx": (".jsx", "text/javascript"),
    "html": (".html", "text/html"),
    "css": (".css", "text/css"),
    "json": (".json", "application/json"),
    "yaml": (".yaml", "application/yaml"),
    "yml": (".yaml", "application/yaml"),
    "toml": (".toml", "application/toml"),
    "sql": (".sql", "application/sql"),
    "sh": (".sh", "text/x-shellscript"),
    "bash": (".sh", "text/x-shellscript"),
    "zsh": (".sh", "text/x-shellscript"),
    "shell": (".sh", "text/x-shellscript"),
    "java": (".java", "text/x-java"),
    "c": (".c", "text/x-c"),
    "cpp": (".cpp", "text/x-c++"),
    "csharp": (".cs", "text/x-csharp"),
    "cs": (".cs", "text/x-csharp"),
    "ruby": (".rb", "text/x-ruby"),
    "rb": (".rb", "text/x-ruby"),
    "php": (".php", "text/x-php"),
    "swift": (".swift", "text/x-swift"),
    "kotlin": (".kt", "text/x-kotlin"),
    "markdown": (".md", "text/markdown"),
    "md": (".md", "text/markdown"),
    "xml": (".xml", "application/xml"),
    "diff": (".diff", "text/x-diff"),
    "patch": (".diff", "text/x-diff"),
}

UNKNOWN = (".txt", "text/plain")


@dataclass(slots=True)
class CodeBlock:
    index: int
    language: str | None
    content: str
    filename: str
    mime: str


def language_file(language: str | None, index: int) -> tuple[str, str]:
    """`(filename, mime)` for a fence. Unknown languages stay `.txt` on purpose."""
    key = (language or "").strip().lower()
    extension, mime = LANGUAGES.get(key, UNKNOWN)
    return f"block-{index + 1}{extension}", mime


def _language_from_info(info: str) -> str | None:
    """The fence's language, ignoring anything after it (`python title=foo`)."""
    token = info.strip().split()[0] if info.strip() else ""
    return token or None


def extract_code_blocks(text: str) -> list[CodeBlock]:
    """Every fenced block in the output, in the order it appeared.

    An unclosed final fence still yields a block: a truncated answer is exactly
    when you most want to see what the model got as far as writing.
    """
    if not text:
        return []

    blocks: list[CodeBlock] = []
    for match in FENCE.finditer(text):
        body = match.group("body")
        if not body.strip():
            continue  # an empty fence is punctuation, not a file
        language = _language_from_info(match.group("info"))
        index = len(blocks)
        filename, mime = language_file(language, index)
        blocks.append(
            CodeBlock(
                index=index,
                language=language,
                content=body,
                filename=filename,
                mime=mime,
            )
        )
    return blocks
