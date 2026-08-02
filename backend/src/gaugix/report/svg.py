"""Hand-built inline SVG charts for exported reports (PRD F5.5).

A report has to open offline from a single file, so no chart library and no
web fonts: every chart here is a string of SVG with the colours baked in.
That constraint is also a feature — the markup is small enough to unit-test,
which is how we know a 0% bar is drawn as an empty bar rather than skipped.

Conventions shared by every chart:

* colours come from `PALETTE`, matching the app's verdict semantics so a green
  means "passed" here exactly as it does in the UI;
* nothing is drawn from data the caller did not supply — a `None` pass rate
  renders as "not scored", never as zero;
* every chart carries a `<title>` for screen readers and hover text.
"""

from __future__ import annotations

from html import escape

#: Verdict semantics, kept in step with `index.css`. Hex rather than oklch so
#: the file opens the same way in an old browser or an email preview pane.
PALETTE = {
    "pass": "#3f9f6f",
    "fail": "#d4564a",
    "error": "#c98a2e",
    "pending": "#8b8f98",
    "human": "#8b62c4",
    "ink": "#2b2f36",
    "muted": "#6b7280",
    "grid": "#e3e6ea",
    "accent": "#2f8f9d",
}

BAR_HEIGHT = 22
BAR_GAP = 10
LABEL_WIDTH = 190
VALUE_WIDTH = 64


def _text(
    x: float,
    y: float,
    content: str,
    *,
    fill: str,
    size: int = 12,
    anchor: str = "start",
    weight: str = "normal",
) -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" fill="{fill}" font-size="{size}" '
        f'text-anchor="{anchor}" font-weight="{weight}" '
        f'font-family="ui-sans-serif, system-ui, sans-serif">{escape(content)}</text>'
    )


def _pct(value: float | None) -> str:
    return "not scored" if value is None else f"{value:g}%"


def bar_chart(rows: list[tuple[str, float | None]], *, width: int = 560, title: str = "") -> str:
    """Horizontal bars, one per row. `None` renders as an explicit "not scored".

    Used for pass rate per executor — the single most-read number in a report.
    """
    if not rows:
        return empty_chart("Nothing to chart yet")

    height = len(rows) * (BAR_HEIGHT + BAR_GAP) + 12
    track = width - LABEL_WIDTH - VALUE_WIDTH
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img">'
    ]
    if title:
        parts.append(f"<title>{escape(title)}</title>")

    for index, (label, value) in enumerate(rows):
        y = index * (BAR_HEIGHT + BAR_GAP) + 6
        mid = y + BAR_HEIGHT / 2 + 4
        parts.append(_text(0, mid, _truncate(label, 28), fill=PALETTE["ink"]))
        parts.append(
            f'<rect x="{LABEL_WIDTH}" y="{y}" width="{track}" height="{BAR_HEIGHT}" '
            f'rx="3" fill="{PALETTE["grid"]}" />'
        )
        if value is not None:
            filled = max(0.0, min(100.0, value)) / 100 * track
            colour = PALETTE["pass"] if value >= 50 else PALETTE["fail"]
            # A genuine 0% still gets a hairline, so "scored and failed
            # everything" never looks like "not measured".
            parts.append(
                f'<rect x="{LABEL_WIDTH}" y="{y}" width="{max(filled, 1.5):.1f}" '
                f'height="{BAR_HEIGHT}" rx="3" fill="{colour}" />'
            )
        parts.append(
            _text(
                width,
                mid,
                _pct(value),
                fill=PALETTE["ink"] if value is not None else PALETTE["muted"],
                anchor="end",
            )
        )

    parts.append("</svg>")
    return "".join(parts)


def stacked_bar(passed: int, failed: int, unscored: int, *, width: int = 560) -> str:
    """One bar showing the verdict split. Unscored is its own segment, never hidden."""
    total = passed + failed + unscored
    if total == 0:
        return empty_chart("No items")

    height = 40
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img">',
        f"<title>{passed} passed, {failed} failed, {unscored} unscored</title>",
    ]
    x = 0.0
    for count, colour, label in (
        (passed, PALETTE["pass"], "passed"),
        (failed, PALETTE["fail"], "failed"),
        (unscored, PALETTE["pending"], "unscored"),
    ):
        if count == 0:
            continue
        segment = count / total * width
        parts.append(
            f'<rect x="{x:.1f}" y="0" width="{segment:.1f}" height="22" fill="{colour}" />'
        )
        if segment > 46:
            parts.append(
                _text(x + segment / 2, 16, str(count), fill="#ffffff", anchor="middle", size=12)
            )
        parts.append(_text(x, 36, label, fill=PALETTE["muted"], size=11))
        x += segment

    parts.append("</svg>")
    return "".join(parts)


def delta_chart(rows: list[tuple[str, float]], *, width: int = 560) -> str:
    """Signed score deltas around a centre line — improvements right, regressions left."""
    if not rows:
        return empty_chart("No score changes")

    height = len(rows) * (BAR_HEIGHT + BAR_GAP) + 12
    centre = LABEL_WIDTH + (width - LABEL_WIDTH - VALUE_WIDTH) / 2
    half = (width - LABEL_WIDTH - VALUE_WIDTH) / 2
    span = max((abs(value) for _, value in rows), default=1) or 1

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img">',
        f'<line x1="{centre:.1f}" y1="0" x2="{centre:.1f}" y2="{height}" '
        f'stroke="{PALETTE["grid"]}" stroke-width="1" />',
    ]
    for index, (label, value) in enumerate(rows):
        y = index * (BAR_HEIGHT + BAR_GAP) + 6
        mid = y + BAR_HEIGHT / 2 + 4
        length = abs(value) / span * half
        x = centre if value >= 0 else centre - length
        colour = PALETTE["pass"] if value >= 0 else PALETTE["fail"]
        parts.append(_text(0, mid, _truncate(label, 28), fill=PALETTE["ink"]))
        parts.append(
            f'<rect x="{x:.1f}" y="{y}" width="{max(length, 1.5):.1f}" '
            f'height="{BAR_HEIGHT}" rx="3" fill="{colour}" />'
        )
        parts.append(_text(width, mid, f"{value:+g}", fill=PALETTE["ink"], anchor="end"))
    parts.append("</svg>")
    return "".join(parts)


def sparkline(values: list[float], *, width: int = 120, height: int = 28) -> str:
    """A tiny trend line — used for pass rate across recent runs."""
    if len(values) < 2:
        return ""
    low, high = min(values), max(values)
    span = (high - low) or 1
    step = width / (len(values) - 1)
    points = " ".join(
        f"{index * step:.1f},{height - (value - low) / span * (height - 4) - 2:.1f}"
        for index, value in enumerate(values)
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img">'
        f"<title>trend: {values[0]:g} to {values[-1]:g}</title>"
        f'<polyline points="{points}" fill="none" stroke="{PALETTE["accent"]}" '
        f'stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round" />'
        f"</svg>"
    )


def empty_chart(message: str) -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 560 40" width="560" height="40" '
        f'role="img"><title>{escape(message)}</title>'
        + _text(0, 24, message, fill=PALETTE["muted"], size=12)
        + "</svg>"
    )


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
