"""Generated SVG markup — the charts a report cannot re-render if they are wrong."""

from __future__ import annotations

import re
from xml.etree import ElementTree

from gaugix.report import svg


def parse(markup: str) -> ElementTree.Element:
    """Every chart must be well-formed XML, or a browser may drop it silently.

    The stdlib parser is safe here on purpose: the only input is markup this
    module just generated, which contains no doctype and no entities, so the
    XXE and entity-expansion attacks that would justify `defusedxml` have no
    way in. Nothing external is ever parsed.
    """
    return ElementTree.fromstring(markup)


def rect_widths(markup: str) -> list[float]:
    return [float(w) for w in re.findall(r'<rect[^>]*\swidth="([\d.]+)"', markup)]


def rect_xs(markup: str) -> list[float]:
    # The leading space matters: without it this also matches the `rx="3"` corner radius.
    return [float(x) for x in re.findall(r'<rect[^>]*\sx="([\d.]+)"', markup)]


def legend_labels(markup: str) -> list[str]:
    return re.findall(r"font-size=\"11\"[^>]*>([a-z]+)</text>", markup)


# -- bar chart -----------------------------------------------------------------


def test_a_bar_chart_is_well_formed_svg():
    root = parse(svg.bar_chart([("gpt-4o-mini", 75.0)]))
    assert root.tag.endswith("svg")


def test_a_bar_is_proportional_to_its_value():
    half = svg.bar_chart([("a", 50.0)])
    full = svg.bar_chart([("a", 100.0)])
    # Each row draws a track plus a fill; the fill is the second rect.
    assert rect_widths(full)[1] > rect_widths(half)[1]
    assert rect_widths(half)[1] == rect_widths(full)[1] / 2


def test_zero_percent_still_draws_a_bar():
    """0% is a measured result. Drawing nothing would read as "not measured"."""
    markup = svg.bar_chart([("a", 0.0)])
    assert rect_widths(markup)[1] > 0
    assert ">0%<" in markup


def test_an_unscored_row_says_so_instead_of_drawing_zero():
    markup = svg.bar_chart([("a", None)])
    assert "not scored" in markup
    # Track only — no fill rect, because there is nothing to fill in.
    assert len(rect_widths(markup)) == 1


def test_a_passing_bar_and_a_failing_bar_use_different_colours():
    assert svg.PALETTE["pass"] in svg.bar_chart([("a", 80.0)])
    assert svg.PALETTE["fail"] in svg.bar_chart([("a", 20.0)])


def test_a_value_above_the_scale_cannot_overflow_the_track():
    markup = svg.bar_chart([("a", 250.0)])
    track, fill = rect_widths(markup)[0], rect_widths(markup)[1]
    assert fill <= track


def test_a_long_label_is_truncated_rather_than_overlapping():
    markup = svg.bar_chart([("x" * 80, 50.0)])
    assert "…" in markup


def test_labels_are_escaped():
    markup = svg.bar_chart([("<script>alert(1)</script>", 50.0)])
    assert "<script>" not in markup
    assert "&lt;script&gt;" in markup


def test_an_empty_chart_explains_itself():
    markup = svg.bar_chart([])
    assert "Nothing to chart" in markup
    parse(markup)


# -- stacked bar ---------------------------------------------------------------


def test_the_stacked_bar_segments_fill_the_width():
    markup = svg.stacked_bar(2, 1, 1, width=400)
    assert abs(sum(rect_widths(markup)) - 400) < 0.5


def test_unscored_gets_its_own_visible_segment():
    """Folding unscored into failed would overstate failure (D-014)."""
    markup = svg.stacked_bar(1, 0, 3)
    assert "unscored" in markup
    assert svg.PALETTE["pending"] in markup


def test_an_absent_bucket_draws_nothing():
    """An empty segment gets no rect and no legend entry — but the title still counts it."""
    markup = svg.stacked_bar(4, 0, 0)
    assert legend_labels(markup) == ["passed"]
    assert len(rect_widths(markup)) == 1
    assert "0 failed" in markup  # the honest total is still stated


def test_a_run_with_no_items_says_so():
    assert "No items" in svg.stacked_bar(0, 0, 0)


def test_the_stacked_bar_title_reports_the_real_counts():
    assert "<title>3 passed, 2 failed, 1 unscored</title>" in svg.stacked_bar(3, 2, 1)


# -- delta chart ---------------------------------------------------------------


def test_improvements_and_regressions_land_on_opposite_sides():
    markup = svg.delta_chart([("up", 12.0), ("down", -12.0)])
    xs = rect_xs(markup)
    assert xs[0] > xs[1]


def test_a_delta_is_labelled_with_its_sign():
    markup = svg.delta_chart([("a", 7.5), ("b", -3.0)])
    assert "+7.5" in markup
    assert "-3" in markup


def test_no_score_changes_is_stated_not_blank():
    assert "No score changes" in svg.delta_chart([])


# -- sparkline -----------------------------------------------------------------


def test_a_sparkline_needs_at_least_two_points():
    assert svg.sparkline([50.0]) == ""
    assert svg.sparkline([]) == ""


def test_a_sparkline_plots_every_point():
    markup = svg.sparkline([10.0, 50.0, 30.0])
    points = re.search(r'points="([^"]+)"', markup)
    assert points is not None
    assert len(points.group(1).split()) == 3
    parse(markup)


def test_a_flat_sparkline_does_not_divide_by_zero():
    markup = svg.sparkline([40.0, 40.0, 40.0])
    parse(markup)
