#pragma once

#include "draw.hpp"

#include <absl/container/inlined_vector.h>

#include <algorithm>
#include <string>

struct TextVisualLine {
    u32 row = 0;
    u32 begin_byte = 0;
    u32 end_byte = 0;
};

i32 text_visual_rune_width(
    char32_t codepoint,
    i32 cell
) {
    return codepoint == U'\t'
        ? 4 - (cell % 4)
        : display_rune(codepoint).width;
}

inline i32 text_visual_cluster_width(
    const std::string& line,
    u32 begin_byte,
    u32 end_byte,
    i32 cell
) {
    i32 width = 0;

    for (u32 byte = begin_byte; byte < end_byte;) {
        const Rune rune = decode_utf8(line, byte);
        width += text_visual_rune_width(
            rune.codepoint,
            cell + width
        );
        byte += rune.bytes;
    }

    return width;
}

inline TextVisualLine wrapped_text_line(
    const TextCardData& data,
    u32 row,
    u32 begin_byte,
    i32 width
) {
    const std::string& line = data.lines[row];
    u32 end_byte = begin_byte;
    i32 cell = 0;

    while (end_byte < line.size()) {
        const u32 cluster_end = next_text_cluster_byte(
            line,
            end_byte
        );
        const i32 cluster_width = text_visual_cluster_width(
            line,
            end_byte,
            cluster_end,
            cell
        );

        if (cell + cluster_width > width) {
            if (cell == 0) {
                end_byte = cluster_end;
            }
            break;
        }

        cell += cluster_width;
        end_byte = cluster_end;
    }

    return {row, begin_byte, end_byte};
}

inline TextVisualLine wrapped_text_line_at(
    const TextCardData& data,
    TextPos position,
    i32 width
) {
    u32 begin_byte = 0;

    for (;;) {
        const TextVisualLine line = wrapped_text_line(
            data,
            position.row,
            begin_byte,
            width
        );

        if (
            position.byte < line.end_byte ||
            line.end_byte == data.lines[position.row].size()
        ) {
            return line;
        }

        begin_byte = line.end_byte;
    }
}

inline TextVisualLine wrapped_text_cursor_line(
    const TextCardData& data,
    const TextSession& session,
    i32 width
) {
    if (session.wrap_end_affinity) {
        u32 begin_byte = 0;

        for (;;) {
            const TextVisualLine line = wrapped_text_line(
                data,
                session.cursor.row,
                begin_byte,
                width
            );

            if (
                line.end_byte == session.cursor.byte &&
                line.end_byte < data.lines[line.row].size()
            ) {
                return line;
            }

            if (
                session.cursor.byte <= line.end_byte ||
                line.end_byte == data.lines[line.row].size()
            ) {
                break;
            }

            begin_byte = line.end_byte;
        }
    }

    return wrapped_text_line_at(data, session.cursor, width);
}

inline bool next_wrapped_text_line(
    const TextCardData& data,
    TextVisualLine& line,
    i32 width
) {
    if (line.end_byte < data.lines[line.row].size()) {
        line = wrapped_text_line(
            data,
            line.row,
            line.end_byte,
            width
        );
        return true;
    }

    if (line.row + 1 >= data.lines.size()) {
        return false;
    }

    line = wrapped_text_line(data, line.row + 1, 0, width);
    return true;
}

inline TextVisualLine last_wrapped_text_line(
    const TextCardData& data,
    u32 row,
    i32 width
) {
    TextVisualLine line = wrapped_text_line(data, row, 0, width);

    while (line.end_byte < data.lines[row].size()) {
        line = wrapped_text_line(
            data,
            row,
            line.end_byte,
            width
        );
    }

    return line;
}

inline bool previous_wrapped_text_lines(
    const TextCardData& data,
    TextVisualLine& line,
    i32 width,
    u32 count
) {
    if (count == 0) {
        return false;
    }

    const TextVisualLine original = line;

    if (count == 1) {
        if (line.begin_byte == 0) {
            if (line.row == 0) {
                return false;
            }

            line = last_wrapped_text_line(data, line.row - 1, width);
            return true;
        }

        TextVisualLine previous = wrapped_text_line(
            data,
            line.row,
            0,
            width
        );

        while (previous.end_byte != line.begin_byte) {
            previous = wrapped_text_line(
                data,
                line.row,
                previous.end_byte,
                width
            );
        }

        line = previous;
        return true;
    }

    u32 remaining = count;
    u32 row = line.row;
    bool current_row = true;
    absl::InlinedVector<TextVisualLine, 80> recent;
    recent.reserve(count);

    for (;;) {
        recent.clear();
        std::size_t oldest = 0;
        u32 total = 0;
        TextVisualLine visual = wrapped_text_line(data, row, 0, width);

        const auto remember = [&](TextVisualLine value) {
            if (recent.size() < remaining) {
                recent.push_back(value);
            } else {
                recent[oldest] = value;
                oldest = (oldest + 1) % recent.size();
            }
            ++total;
        };

        if (current_row) {
            while (visual.begin_byte != line.begin_byte) {
                remember(visual);
                visual = wrapped_text_line(
                    data,
                    row,
                    visual.end_byte,
                    width
                );
            }
        } else {
            for (;;) {
                remember(visual);

                if (visual.end_byte == data.lines[row].size()) {
                    break;
                }

                visual = wrapped_text_line(
                    data,
                    row,
                    visual.end_byte,
                    width
                );
            }
        }

        if (total >= remaining) {
            line = recent[oldest];
            return true;
        }

        remaining -= total;

        if (row == 0) {
            line = wrapped_text_line(data, 0, 0, width);
            return
                line.row != original.row ||
                line.begin_byte != original.begin_byte;
        }

        --row;
        current_row = false;
    }
}

inline bool previous_wrapped_text_line(
    const TextCardData& data,
    TextVisualLine& line,
    i32 width
) {
    return previous_wrapped_text_lines(data, line, width, 1);
}

inline bool text_visual_line_less(
    TextVisualLine lhs,
    TextVisualLine rhs
) {
    return
        lhs.row < rhs.row ||
        (lhs.row == rhs.row && lhs.begin_byte < rhs.begin_byte);
}

inline bool same_text_visual_line(
    TextVisualLine lhs,
    TextVisualLine rhs
) {
    return
        lhs.row == rhs.row &&
        lhs.begin_byte == rhs.begin_byte;
}

inline i32 wrapped_text_cell(
    const TextCardData& data,
    TextVisualLine visual,
    u32 target_byte
) {
    const std::string& line = data.lines[visual.row];
    i32 cell = 0;

    for (u32 byte = visual.begin_byte; byte < target_byte;) {
        const Rune rune = decode_utf8(line, byte);
        cell += text_visual_rune_width(rune.codepoint, cell);
        byte += rune.bytes;
    }

    return cell;
}

inline u32 wrapped_text_byte_at_cell(
    const TextCardData& data,
    TextVisualLine visual,
    i32 target_cell
) {
    const std::string& line = data.lines[visual.row];
    i32 cell = 0;

    for (u32 byte = visual.begin_byte;
         byte < visual.end_byte;) {
        if (target_cell <= cell) {
            return byte;
        }

        const u32 cluster_end = next_text_cluster_byte(line, byte);
        const i32 width = text_visual_cluster_width(
            line,
            byte,
            cluster_end,
            cell
        );

        if (target_cell < cell + width) {
            return byte;
        }

        cell += width;
        byte = cluster_end;
    }

    return visual.end_byte;
}

inline u32 draw_text_line(
    Screen& screen,
    i32 left,
    i32 y,
    i32 width,
    const TextCardData& data,
    const TextStyles& styles,
    u32 row,
    u32 begin_byte,
    u32 end_byte,
    i32 first_cell,
    Style base_style,
    CardId owner,
    TextStyleCursor& style_cursor,
    bool soft_wrap = false
) {
    const std::string& line = data.lines[row];
    const i32 right = left + width;
    i32 cell = 0;

    for (u32 byte = begin_byte; byte < end_byte;) {
        const Rune rune = decode_utf8(line, byte);

        while (
            style_cursor.row < styles.size() &&
            styles[style_cursor.row].row < row
        ) {
            ++style_cursor.row;
            style_cursor.span = 0;
        }

        Style style = base_style;

        if (
            style_cursor.row < styles.size() &&
            styles[style_cursor.row].row == row
        ) {
            const RowTextSpans& row_spans =
                styles[style_cursor.row].spans;

            while (
                style_cursor.span < row_spans.size() &&
                row_spans[style_cursor.span].end_byte <= byte
            ) {
                ++style_cursor.span;
            }

            if (
                style_cursor.span < row_spans.size() &&
                row_spans[style_cursor.span].begin_byte <= byte
            ) {
                style = row_spans[style_cursor.span].style;
            }
        }

        if (rune.codepoint == U'\t') {
            const i32 count = 4 - (cell % 4);

            if (soft_wrap && cell + count > width) {
                return byte;
            }

            for (i32 i = 0; i < count; ++i) {
                const i32 screen_x = left + cell - first_cell;

                if (screen_x >= right) {
                    return byte;
                }

                if (screen_x >= left) {
                    screen.paint(
                        screen_x,
                        y,
                        {U' ', 1},
                        style,
                        owner,
                        row,
                        byte
                    );
                }

                ++cell;
            }

            byte += rune.bytes;
            continue;
        }

        const DisplayRune display = display_rune(rune.codepoint);

        if (soft_wrap && cell + display.width > width) {
            return byte;
        }

        const i32 screen_x = left + cell - first_cell;

        if (screen_x >= right) {
            return byte;
        }

        if (
            screen_x >= left &&
            screen_x + display.width <= right
        ) {
            screen.paint(
                screen_x,
                y,
                display,
                style,
                owner,
                row,
                byte
            );
        }

        cell += display.width;
        byte += rune.bytes;
    }

    return end_byte;
}

inline void draw_text_selection(
    Screen& screen,
    CardId id,
    i32 left,
    i32 top,
    i32 width,
    i32 height,
    const TextSession& session
) {
    const TextRange selection = session.selection();

    if (selection.begin == selection.end) {
        return;
    }

    const i32 screen_left = std::max(0, left);
    const i32 screen_top = std::max(0, top);
    const i32 screen_right = static_cast<i32>(std::min<i64>(
        screen.width(),
        static_cast<i64>(left) + width
    ));
    const i32 screen_bottom = static_cast<i32>(std::min<i64>(
        screen.height(),
        static_cast<i64>(top) + height
    ));

    for (i32 y = screen_top; y < screen_bottom; ++y) {
        for (i32 x = screen_left; x < screen_right; ++x) {
            const ScreenCell& cell = screen.at(x, y);

            if (
                cell.owner == id &&
                cell.width != 0 &&
                cell.text_row != ~u32{0} &&
                text_range_contains(
                    selection,
                    TextPos{cell.text_row, cell.text_byte}
                )
            ) {
                screen.invert(x, y);
            }
        }
    }
}

void draw_text_card(
    Screen& screen,
    const CardData& card_data,
    CardId id,
    i32 x,
    i32 y,
    const CardFormat& format,
    CardVisualState visual_state,
    const FormatSession* active_session
) {
    const TextCardData& data = std::get<TextCardData>(card_data);
    const TextSession* session =
        active_session == nullptr
            ? nullptr
            : &std::get<TextSession>(*active_session);
    const Extent extent = format.measure(card_data);
    const i32 content_x = x + (format.borderless ? 0 : 1);
    const i32 content_y = y + (format.borderless ? 0 : 1);

    if (format.borderless) {
        screen.fill(
            x,
            y,
            extent.width,
            extent.height,
            format.body,
            id
        );
    } else {
        draw_box(
            screen,
            extent,
            id,
            x,
            y,
            format,
            visual_state
        );
    }

    const i32 inner_width = data.layout.width - 2;
    const i32 inner_height = data.layout.height - 2;
    const VisibleRowRange rows = visible_rows(
        screen,
        content_y,
        inner_height
    );
    TextVisualLine cursor_visual{};
    i32 cursor_visual_row = -1;
    TextStyleCursor style_cursor;

    if (format.soft_wrap) {
        TextVisualLine visual{
            session == nullptr ? 0 : session->wrap_scroll.row,
            session == nullptr ? 0 : session->wrap_scroll.byte,
            0,
        };
        bool content = true;

        for (i32 local_row = 0;
             local_row < rows.first;
             ++local_row) {
            visual = wrapped_text_line(
                data,
                visual.row,
                visual.begin_byte,
                inner_width
            );

            if (visual.end_byte < data.lines[visual.row].size()) {
                visual.begin_byte = visual.end_byte;
            } else if (visual.row + 1 < data.lines.size()) {
                ++visual.row;
                visual.begin_byte = 0;
            } else {
                content = false;
                break;
            }
        }

        if (content) {
            style_cursor = text_style_index(
                data.styles,
                visual.row,
                visual.begin_byte
            );
        }

        for (i32 local_row = rows.first;
             content && local_row < rows.last;
             ++local_row) {
            const Style base =
                format.first_line_is_title && visual.row == 0
                    ? format.title
                    : format.body;
            visual.end_byte = draw_text_line(
                screen,
                content_x,
                content_y + local_row,
                inner_width,
                data,
                data.styles,
                visual.row,
                visual.begin_byte,
                static_cast<u32>(data.lines[visual.row].size()),
                0,
                base,
                id,
                style_cursor,
                true
            );

            if (
                session != nullptr &&
                session->cursor.row == visual.row &&
                session->cursor.byte >= visual.begin_byte &&
                (session->cursor.byte < visual.end_byte ||
                 (session->cursor.byte == visual.end_byte &&
                  (visual.end_byte == data.lines[visual.row].size() ||
                   session->wrap_end_affinity)))
            ) {
                cursor_visual = visual;
                cursor_visual_row = local_row;
            }

            if (visual.end_byte < data.lines[visual.row].size()) {
                visual.begin_byte = visual.end_byte;
            } else if (visual.row + 1 < data.lines.size()) {
                ++visual.row;
                visual.begin_byte = 0;
            } else {
                break;
            }
        }
    } else {
        const u32 scroll_row =
            session == nullptr ? 0 : session->scroll_row;
        const i32 scroll_cell =
            session == nullptr ? 0 : session->scroll_cell;
        style_cursor = text_style_index(
            data.styles,
            scroll_row + static_cast<u32>(rows.first),
            0
        );

        for (i32 local_row = rows.first;
             local_row < rows.last;
             ++local_row) {
            const u32 row =
                scroll_row + static_cast<u32>(local_row);

            if (row >= data.lines.size()) {
                break;
            }

            const Style base =
                format.first_line_is_title && row == 0
                    ? format.title
                    : format.body;

            draw_text_line(
                screen,
                content_x,
                content_y + local_row,
                inner_width,
                data,
                data.styles,
                row,
                0,
                static_cast<u32>(data.lines[row].size()),
                scroll_cell,
                base,
                id,
                style_cursor
            );
        }
    }

    if (session == nullptr) {
        return;
    }

    draw_text_selection(
        screen,
        id,
        content_x,
        content_y,
        inner_width,
        inner_height,
        *session
    );

    const TextRange selection = session->selection();

    if (
        format.soft_wrap &&
        selection.begin == selection.end
    ) {
        if (cursor_visual_row >= 0) {
            const i32 cursor_x = std::min(
                wrapped_text_cell(
                    data,
                    cursor_visual,
                    session->cursor.byte
                ),
                inner_width - 1
            );

            screen.invert(
                content_x + cursor_x,
                content_y + cursor_visual_row
            );
        }

        return;
    }

    if (
        selection.begin == selection.end &&
        session->cursor.row >= session->scroll_row &&
        session->cursor.row <
            session->scroll_row + static_cast<u32>(inner_height)
    ) {
        const i32 cursor_x = cell_column(
            data.lines[session->cursor.row],
            session->cursor.byte
        ) - session->scroll_cell;

        if (cursor_x >= 0 && cursor_x < inner_width) {
            screen.invert(
                content_x + cursor_x,
                content_y + static_cast<i32>(
                    session->cursor.row - session->scroll_row
                )
            );
        }
    }
}
