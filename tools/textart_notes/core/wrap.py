"""Cell-aware wrapping helpers shared by prose-oriented renderers."""

from __future__ import annotations

import re

from .cell_width import cell_clusters, expand_tabs, split_prefix, tab_advance, text_width


_TOKEN_RE = re.compile(r"\S+|\s+")


def _hard_chunks(token: str, width: int) -> list[str]:
    chunks: list[str] = []
    rest = token
    while rest:
        prefix, next_rest = split_prefix(rest, width)
        if not prefix:
            raise ValueError("width is too small for the next wide character")
        chunks.append(prefix)
        rest = next_rest
    return chunks


def _clusters(text: str) -> list[str]:
    """Keep every Unicode mark attached while leaving tabs position-aware."""

    return list(cell_clusters(text))


def _cluster_width(cluster: str, column: int) -> int:
    if cluster == "\t":
        return tab_advance(column)
    return text_width(cluster, start=column)


def _render_clusters(clusters: list[str], start_column: int) -> str:
    pieces: list[str] = []
    column = start_column
    for cluster in clusters:
        width = _cluster_width(cluster, column)
        pieces.append(" " * width if cluster == "\t" else cluster)
        column += width
    return "".join(pieces)


def wrap_clusters(text: str, width: int, *, start_column: int = 0) -> list[str]:
    """Greedily wrap one line at terminal-cell cluster boundaries.

    Unlike :func:`wrap_line`, this primitive does not prefer word boundaries;
    it preserves exact cluster order and recomputes physical tab stops from the
    supplied origin on every visual line. It suits compact visual labels whose
    measured rectangle is more important than prose-oriented wrapping.
    """

    if width <= 0:
        raise ValueError("width must be positive")
    if start_column < 0:
        raise ValueError("start_column cannot be negative")
    if "\n" in text or "\r" in text:
        raise ValueError("wrap_clusters accepts one logical line")
    clusters = _clusters(text)
    if not clusters:
        return [""]
    output: list[str] = []
    current: list[str] = []
    used = 0
    for cluster in clusters:
        advance = _cluster_width(cluster, start_column + used)
        if current and used + advance > width:
            output.append(_render_clusters(current, start_column))
            current = []
            used = 0
            advance = _cluster_width(cluster, start_column)
        if advance > width:
            raise ValueError(
                f"width {width} is too small for a {advance}-cell character or tab advance"
            )
        current.append(cluster)
        used += advance
    output.append(_render_clusters(current, start_column))
    return output


def _wrap_tabbed(text: str, width: int, start_column: int) -> list[str]:
    """Wrap a tabbed line while recomputing stops at each visual-line origin."""

    remaining = _clusters(text.rstrip(" "))
    if not remaining:
        return [""]
    output: list[str] = []
    while remaining:
        used = 0
        fit = 0
        while fit < len(remaining):
            advance = _cluster_width(remaining[fit], start_column + used)
            if used + advance > width:
                break
            used += advance
            fit += 1
        if fit == 0:
            needed = _cluster_width(remaining[0], start_column)
            raise ValueError(
                f"width {width} is too small for a {needed}-cell character or tab advance"
            )
        consume = fit
        segment = remaining[:fit]
        if fit < len(remaining):
            boundary: int | None = None
            for index in range(1, fit):
                if remaining[index] == "\t" or remaining[index].isspace():
                    boundary = index
            if boundary is not None:
                segment = remaining[:boundary]
                consume = boundary
                while consume < len(remaining) and (
                    remaining[consume] == "\t" or remaining[consume].isspace()
                ):
                    consume += 1
        output.append(_render_clusters(segment, start_column).rstrip(" "))
        remaining = remaining[consume:]
    return output


def wrap_preserving_line(text: str, width: int, *, start_column: int = 0) -> list[str]:
    """Wrap one hard line without discarding ordinary whitespace.

    Tabs are rasterized from the physical start column of every visual line.
    A break prefers the last whitespace cluster that fits, but the cluster is
    retained at the end of that line so source excerpts remain faithful.
    """

    if width <= 0:
        raise ValueError("width must be positive")
    if start_column < 0:
        raise ValueError("start_column cannot be negative")
    clusters = _clusters(text)
    if not clusters:
        return [""]
    output: list[str] = []
    start = 0
    while start < len(clusters):
        used = 0
        end = start
        while end < len(clusters):
            advance = _cluster_width(clusters[end], start_column + used)
            if used + advance > width:
                break
            used += advance
            end += 1
        if end == start:
            needed = _cluster_width(clusters[start], start_column)
            raise ValueError(
                f"width {width} is too small for a {needed}-cell character or tab advance"
            )
        if end < len(clusters):
            boundary: int | None = None
            saw_visible = False
            for index in range(start, end):
                if clusters[index] == "\t" or clusters[index].isspace():
                    if saw_visible:
                        boundary = index + 1
                else:
                    saw_visible = True
            if boundary is not None:
                end = boundary
        output.append(_render_clusters(clusters[start:end], start_column))
        start = end
    return output


def wrap_preserving_text(text: str, width: int, *, start_column: int = 0) -> list[str]:
    """Wrap all hard lines while retaining empty lines and ordinary spaces."""

    output: list[str] = []
    for hard_line in text.split("\n"):
        output.extend(wrap_preserving_line(hard_line, width, start_column=start_column))
    return output


def wrap_line(text: str, width: int, *, start_column: int = 0) -> list[str]:
    """Greedily wrap one line while retaining words when they fit."""

    if width <= 0:
        raise ValueError("width must be positive")
    if start_column < 0:
        raise ValueError("start_column cannot be negative")
    if "\t" in text:
        return _wrap_tabbed(text, width, start_column)
    source = text.strip()
    if not source:
        return [""]

    lines: list[str] = []
    current = ""
    pending_space = False
    for token in _TOKEN_RE.findall(source):
        if token.isspace():
            pending_space = bool(current)
            continue
        separator = " " if pending_space and current else ""
        candidate = current + separator + token
        if text_width(candidate) <= width:
            current = candidate
            pending_space = False
            continue
        if current:
            lines.append(current)
            current = ""
        if text_width(token) <= width:
            current = token
        else:
            chunks = _hard_chunks(token, width)
            lines.extend(chunks[:-1])
            current = chunks[-1]
        pending_space = False
    if current or not lines:
        lines.append(current)
    return lines


def wrap_text(
    text: str,
    width: int,
    *,
    initial_indent: str = "",
    subsequent_indent: str = "",
) -> list[str]:
    """Wrap possibly multi-line text with optional hanging indentation."""

    initial_available = width - text_width(initial_indent)
    later_available = width - text_width(subsequent_indent)
    if initial_available <= 0 or later_available <= 0:
        raise ValueError("indent leaves no room for text")
    output: list[str] = []
    first_visual_line = True
    for logical_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if logical_line == "":
            output.append(initial_indent if first_visual_line else subsequent_indent)
            first_visual_line = False
            continue
        remaining = expand_tabs(logical_line).strip()
        while remaining:
            indent = initial_indent if first_visual_line else subsequent_indent
            available = initial_available if first_visual_line else later_available
            # Prefer a word boundary, but guarantee progress for CJK and long tokens.
            prefix, rest = split_prefix(remaining, available)
            if not prefix:
                raise ValueError("available width cannot hold the next character")
            if rest and not rest[0].isspace() and " " in prefix:
                word_prefix = prefix.rsplit(" ", 1)[0]
                if word_prefix:
                    rest = remaining[len(word_prefix):]
                    prefix = word_prefix
            output.append(indent + prefix.rstrip())
            remaining = rest.lstrip()
            first_visual_line = False
    return output or [initial_indent]
