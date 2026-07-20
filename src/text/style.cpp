#include "style.hpp"

#include <absl/container/inlined_vector.h>

#include <algorithm>
#include <utility>
#include <vector>

static void append_row_text_span(
    RowTextSpans& spans,
    TextSpan span
) {
    if (span.begin_byte >= span.end_byte) {
        return;
    }

    if (
        !spans.empty() &&
        spans.back().end_byte == span.begin_byte &&
        spans.back().style == span.style
    ) {
        spans.back().end_byte = span.end_byte;
        return;
    }

    spans.push_back(span);
}

static void append_canonical_text_span(
    TextStyles& styles,
    TextSpan span
) {
    if (span.begin_byte >= span.end_byte) {
        return;
    }

    if (styles.empty() || styles.back().row != span.row) {
        styles.emplace_back(span.row);
    }

    append_row_text_span(styles.back().spans, span);
}

void apply_text_span(
    TextStyles& styles,
    TextSpan applied
) {
    if (applied.begin_byte >= applied.end_byte) {
        return;
    }

    applied.style = canonical_style(applied.style);
    const auto row = std::lower_bound(
        styles.begin(),
        styles.end(),
        applied.row,
        [](const RowStyles& candidate, u32 target) {
            return candidate.row < target;
        }
    );

    if (row == styles.end() || row->row != applied.row) {
        styles.insert(row, RowStyles{applied.row, applied});
        return;
    }

    RowTextSpans result;
    result.reserve(row->spans.size() + 2);
    bool inserted = false;

    for (const TextSpan& span : row->spans) {
        if (span.end_byte <= applied.begin_byte) {
            append_row_text_span(result, span);
            continue;
        }

        if (span.begin_byte >= applied.end_byte) {
            if (!inserted) {
                append_row_text_span(result, applied);
                inserted = true;
            }

            append_row_text_span(result, span);
            continue;
        }

        if (span.begin_byte < applied.begin_byte) {
            append_row_text_span(result, {
                span.row,
                span.begin_byte,
                applied.begin_byte,
                span.style,
            });
        }

        if (!inserted) {
            append_row_text_span(result, applied);
            inserted = true;
        }

        if (span.end_byte > applied.end_byte) {
            append_row_text_span(result, {
                span.row,
                applied.end_byte,
                span.end_byte,
                span.style,
            });
        }
    }

    if (!inserted) {
        append_row_text_span(result, applied);
    }

    row->spans = std::move(result);
}

struct TextStyleSweepEvent {
    u32 row = 0;
    u32 byte = 0;
    std::size_t span = 0;
    bool start = false;
};

void canonicalize_text_styles(
    TextStyles& styles,
    const TextLines& lines
) {
    std::vector<TextSpan> spans;
    spans.reserve(text_style_span_count(styles));

    for (const RowStyles& row : styles) {
        if (row.row >= lines.size()) {
            continue;
        }

        const u32 line_size = static_cast<u32>(lines[row.row].size());

        for (TextSpan span : row.spans) {
            span.row = row.row;
            span.begin_byte = std::min(span.begin_byte, line_size);
            span.end_byte = std::min(span.end_byte, line_size);
            span.style = canonical_style(span.style);

            if (span.begin_byte < span.end_byte) {
                spans.push_back(span);
            }
        }
    }

    std::vector<TextStyleSweepEvent> events;
    events.reserve(spans.size() * 2);

    for (std::size_t index = 0; index < spans.size(); ++index) {
        events.push_back({
            spans[index].row,
            spans[index].begin_byte,
            index,
            true,
        });
        events.push_back({
            spans[index].row,
            spans[index].end_byte,
            index,
            false,
        });
    }

    std::sort(
        events.begin(),
        events.end(),
        [](const TextStyleSweepEvent& left,
           const TextStyleSweepEvent& right) {
            if (left.row != right.row) {
                return left.row < right.row;
            }

            if (left.byte != right.byte) {
                return left.byte < right.byte;
            }

            return left.start < right.start;
        }
    );

    TextStyles canonical;
    canonical.reserve(std::min(styles.size(), lines.size()));
    absl::InlinedVector<std::size_t, 16> priorities;
    std::size_t event = 0;

    while (event < events.size()) {
        const u32 row = events[event].row;
        priorities.clear();
        u32 previous_byte = events[event].byte;

        while (event < events.size() && events[event].row == row) {
            const u32 byte = events[event].byte;

            while (
                !priorities.empty() &&
                spans[priorities.front()].end_byte <= previous_byte
            ) {
                std::pop_heap(priorities.begin(), priorities.end());
                priorities.pop_back();
            }

            if (previous_byte < byte && !priorities.empty()) {
                const TextSpan& selected = spans[priorities.front()];
                append_canonical_text_span(canonical, {
                    row,
                    previous_byte,
                    byte,
                    selected.style,
                });
            }

            std::size_t next = event;

            while (
                next < events.size() &&
                events[next].row == row &&
                events[next].byte == byte
            ) {
                if (events[next].start) {
                    priorities.push_back(events[next].span);
                    std::push_heap(priorities.begin(), priorities.end());
                }

                ++next;
            }

            event = next;
            previous_byte = byte;
        }
    }

    styles = std::move(canonical);
}

void canonicalize_text_styles(TextCardData& data) {
    canonicalize_text_styles(data.styles, data.lines);
}

TextStyleCursor text_style_index(
    const TextStyles& styles,
    u32 row,
    u32 byte
) {
    const auto row_position = std::lower_bound(
        styles.begin(),
        styles.end(),
        row,
        [](const RowStyles& candidate, u32 target) {
            return candidate.row < target;
        }
    );
    TextStyleCursor cursor{
        static_cast<std::size_t>(row_position - styles.begin()),
        0,
    };

    if (row_position != styles.end() && row_position->row == row) {
        cursor.span = static_cast<std::size_t>(std::lower_bound(
            row_position->spans.begin(),
            row_position->spans.end(),
            byte,
            [](const TextSpan& span, u32 target) {
                return span.end_byte <= target;
            }
        ) - row_position->spans.begin());
    }

    return cursor;
}

TextStyles text_style_rows(
    const TextStyles& styles,
    u32 first_row,
    u32 last_row
) {
    const auto first = std::lower_bound(
        styles.begin(),
        styles.end(),
        first_row,
        [](const RowStyles& row, u32 target) {
            return row.row < target;
        }
    );
    const auto last = std::upper_bound(
        first,
        styles.end(),
        last_row,
        [](u32 target, const RowStyles& row) {
            return target < row.row;
        }
    );
    return {first, last};
}

void replace_text_style_rows(
    TextStyles& styles,
    u32 first_row,
    u32 last_row,
    const TextStyles& replacement
) {
    const auto first_position = std::lower_bound(
        styles.begin(),
        styles.end(),
        first_row,
        [](const RowStyles& row, u32 target) {
            return row.row < target;
        }
    );
    const auto last_position = std::upper_bound(
        first_position,
        styles.end(),
        last_row,
        [](u32 target, const RowStyles& row) {
            return target < row.row;
        }
    );
    const std::size_t first = static_cast<std::size_t>(
        first_position - styles.begin()
    );
    const std::size_t last = static_cast<std::size_t>(
        last_position - styles.begin()
    );
    styles.erase(styles.begin() + first, styles.begin() + last);
    styles.insert(
        styles.begin() + first,
        replacement.begin(),
        replacement.end()
    );
}

static bool text_span_before(
    const TextSpan& span,
    TextPos position
) {
    return
        span.row < position.row ||
        (span.row == position.row &&
         span.end_byte <= position.byte);
}

static bool text_span_after(
    const TextSpan& span,
    TextPos position
) {
    return
        span.row > position.row ||
        (span.row == position.row &&
         span.begin_byte >= position.byte);
}

TextPos map_text_position_after_edit(
    const TextEdit& edit,
    TextPos position
) {
    if (position.row == edit.old_range.end.row) {
        return {
            edit.new_end.row,
            edit.new_end.byte +
                position.byte - edit.old_range.end.byte,
        };
    }

    if (edit.new_end.row >= edit.old_range.end.row) {
        position.row +=
            edit.new_end.row - edit.old_range.end.row;
    } else {
        position.row -=
            edit.old_range.end.row - edit.new_end.row;
    }

    return position;
}

void edit_text_styles(
    TextStyles& styles,
    const TextEdit& edit
) {
    const auto first_position = std::lower_bound(
        styles.begin(),
        styles.end(),
        edit.old_range.begin.row,
        [](const RowStyles& row, u32 target) {
            return row.row < target;
        }
    );
    const auto last_position = std::upper_bound(
        first_position,
        styles.end(),
        edit.old_range.end.row,
        [](u32 target, const RowStyles& row) {
            return target < row.row;
        }
    );
    const std::size_t first = static_cast<std::size_t>(
        first_position - styles.begin()
    );
    const std::size_t last = static_cast<std::size_t>(
        last_position - styles.begin()
    );
    TextStyles replacement;
    replacement.reserve(last - first + 1);

    for (std::size_t row_index = first; row_index < last; ++row_index) {
        for (TextSpan span : styles[row_index].spans) {
            span.row = styles[row_index].row;

            if (text_span_before(span, edit.old_range.begin)) {
                append_canonical_text_span(replacement, span);
                continue;
            }

            if (!text_span_after(span, edit.old_range.end)) {
                if (
                    span.row == edit.old_range.begin.row &&
                    span.begin_byte < edit.old_range.begin.byte
                ) {
                    append_canonical_text_span(replacement, {
                        span.row,
                        span.begin_byte,
                        edit.old_range.begin.byte,
                        span.style,
                    });
                }

                if (
                    span.row != edit.old_range.end.row ||
                    span.end_byte <= edit.old_range.end.byte
                ) {
                    continue;
                }

                const TextPos begin = map_text_position_after_edit(
                    edit,
                    {span.row, edit.old_range.end.byte}
                );
                const TextPos end = map_text_position_after_edit(
                    edit,
                    {span.row, span.end_byte}
                );
                append_canonical_text_span(replacement, {
                    begin.row,
                    begin.byte,
                    end.byte,
                    span.style,
                });
                continue;
            }

            const TextPos begin = map_text_position_after_edit(
                edit,
                {span.row, span.begin_byte}
            );
            const TextPos end = map_text_position_after_edit(
                edit,
                {span.row, span.end_byte}
            );
            span.row = begin.row;
            span.begin_byte = begin.byte;
            span.end_byte = end.byte;
            append_canonical_text_span(replacement, span);
        }
    }

    styles.erase(styles.begin() + first, styles.begin() + last);

    for (std::size_t index = first; index < styles.size(); ++index) {
        styles[index].row = map_text_position_after_edit(
            edit,
            {styles[index].row, 0}
        ).row;

        for (TextSpan& span : styles[index].spans) {
            span.row = styles[index].row;
        }
    }

    styles.insert(
        styles.begin() + first,
        std::make_move_iterator(replacement.begin()),
        std::make_move_iterator(replacement.end())
    );
}
