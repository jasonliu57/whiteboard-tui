#include "text_edit.hpp"
#include "text_render.hpp"

#include <algorithm>
#include <string>
#include <string_view>
#include <utility>

Extent measure_text_card(const CardData& data) {
    return std::get<TextCardData>(data).layout;
}

void begin_text_card(
    FormatSession& session,
    const CardData&
) {
    session = TextSession{};
}

void rebuild_text_card(CardData& card_data) {
    TextCardData& data = std::get<TextCardData>(card_data);

    if (data.lines.empty()) {
        data.lines.emplace_back();
    }

    canonicalize_text_styles(data);
}

static void keep_wrapped_text_cursor_visible(
    const TextCardData& data,
    TextSession& session
) {
    const i32 inner_width = data.layout.width - 2;
    const i32 inner_height = data.layout.height - 2;
    const TextVisualLine cursor = wrapped_text_cursor_line(
        data,
        session,
        inner_width
    );
    session.wrap_end_affinity =
        cursor.end_byte == session.cursor.byte &&
        cursor.end_byte < data.lines[cursor.row].size();

    TextPos scroll = session.wrap_scroll;

    if (scroll.row >= data.lines.size()) {
        scroll = {cursor.row, cursor.begin_byte};
    } else if (scroll.byte > data.lines[scroll.row].size()) {
        scroll.byte = static_cast<u32>(
            data.lines[scroll.row].size()
        );
    }

    TextVisualLine first = wrapped_text_line_at(
        data,
        scroll,
        inner_width
    );

    if (text_visual_line_less(cursor, first)) {
        first = cursor;
    } else {
        TextVisualLine visible = first;

        for (i32 row = 0; row < inner_height; ++row) {
            if (same_text_visual_line(visible, cursor)) {
                session.wrap_scroll = {
                    first.row,
                    first.begin_byte
                };
                session.scroll_cell = 0;
                return;
            }

            if (!next_wrapped_text_line(
                    data,
                    visible,
                    inner_width
                )) {
                break;
            }
        }

        first = cursor;

        previous_wrapped_text_lines(
            data,
            first,
            inner_width,
            static_cast<u32>(inner_height - 1)
        );
    }

    session.wrap_scroll = {first.row, first.begin_byte};
    session.scroll_cell = 0;
}

static void keep_text_cursor_visible(
    const TextCardData& data,
    TextSession& session,
    bool soft_wrap
) {
    if (soft_wrap) {
        keep_wrapped_text_cursor_visible(data, session);
        return;
    }

    const u32 inner_height =
        static_cast<u32>(data.layout.height - 2);
    const i32 inner_width = data.layout.width - 2;

    if (session.cursor.row < session.scroll_row) {
        session.scroll_row = session.cursor.row;
    } else if (
        session.cursor.row >= session.scroll_row + inner_height
    ) {
        session.scroll_row =
            session.cursor.row - inner_height + 1;
    }

    const i32 column = cell_column(
        data.lines[session.cursor.row],
        session.cursor.byte
    );

    if (column < session.scroll_cell) {
        session.scroll_cell = column;
    } else if (column >= session.scroll_cell + inner_width) {
        session.scroll_cell = column - inner_width + 1;
    }
}

void swap_text_layout_undo(
    TextCardData& data,
    TextSession* session,
    TextLayoutUndo& undo,
    bool soft_wrap
) {
    std::swap(data.layout, undo.layout);

    if (session != nullptr) {
        keep_text_cursor_visible(data, *session, soft_wrap);
    }
}

static void set_text_cursor(
    const TextCardData& data,
    TextSession& session,
    TextPos position,
    bool soft_wrap,
    bool extend_selection,
    bool update_preferred,
    bool wrap_end_affinity = false
) {
    session.cursor = position;
    session.wrap_end_affinity =
        soft_wrap && wrap_end_affinity;

    if (!extend_selection) {
        session.selection_anchor = position;
    }

    if (update_preferred) {
        if (soft_wrap) {
            session.preferred_cell = wrapped_text_cell(
                data,
                wrapped_text_cursor_line(
                    data,
                    session,
                    data.layout.width - 2
                ),
                position.byte
            );
        } else {
            session.preferred_cell = cell_column(
                data.lines[position.row],
                position.byte
            );
        }
    }

    keep_text_cursor_visible(data, session, soft_wrap);
}

FormatAction replace_text_action(
    TextCardData& data,
    TextSession& session,
    TextRange range,
    std::string_view inserted,
    bool soft_wrap,
    std::string replaced
) {
    if (range.begin == range.end && inserted.empty()) {
        return view_action();
    }

    TextUndo undo;
    undo.text = std::move(replaced);

    const TextEdit edit = replace_text_content(
        data,
        &session,
        range,
        inserted,
        true,
        &undo.styles
    );
    undo.range = {range.begin, edit.new_end};
    set_text_cursor(
        data,
        session,
        edit.new_end,
        soft_wrap,
        false,
        true
    );

    return stored_action(FormatUndo{std::move(undo)});
}

FormatAction replace_text_action(
    TextCardData& data,
    TextSession& session,
    TextRange range,
    std::string_view inserted,
    bool soft_wrap
) {
    return replace_text_action(
        data,
        session,
        range,
        inserted,
        soft_wrap,
        extract_text(data.lines, range)
    );
}

void swap_text_undo(
    TextCardData& data,
    TextSession* session,
    TextUndo& undo,
    bool soft_wrap
) {
    std::string replaced = extract_text(data.lines, undo.range);
    TextStyles current_styles = text_style_rows(
        data.styles,
        undo.styles.current_first_row,
        undo.styles.current_last_row
    );
    const TextEdit edit = replace_text_content(
        data,
        session,
        undo.range,
        undo.text
    );
    replace_text_style_rows(
        data.styles,
        undo.styles.replacement_first_row,
        undo.styles.replacement_last_row,
        undo.styles.replacement
    );
    undo.range.end = edit.new_end;
    undo.text = std::move(replaced);
    std::swap(
        undo.styles.current_first_row,
        undo.styles.replacement_first_row
    );
    std::swap(
        undo.styles.current_last_row,
        undo.styles.replacement_last_row
    );
    undo.styles.replacement = std::move(current_styles);

    if (session != nullptr) {
        set_text_cursor(
            data,
            *session,
            edit.new_end,
            soft_wrap,
            false,
            true
        );
    }
}

void swap_text_style_undo(
    TextCardData& data,
    TextStyleUndo& undo
) {
    TextStyles current = text_style_rows(
        data.styles,
        undo.styles.current_first_row,
        undo.styles.current_last_row
    );
    replace_text_style_rows(
        data.styles,
        undo.styles.replacement_first_row,
        undo.styles.replacement_last_row,
        undo.styles.replacement
    );
    std::swap(
        undo.styles.current_first_row,
        undo.styles.replacement_first_row
    );
    std::swap(
        undo.styles.current_last_row,
        undo.styles.replacement_last_row
    );
    undo.styles.replacement = std::move(current);
}

void swap_text_format_undo(
    CardData& card_data,
    FormatSession* format_session,
    FormatUndo& undo,
    bool soft_wrap,
    bool supports_style_undo
) {
    TextCardData& data = std::get<TextCardData>(card_data);
    TextSession* session = format_session == nullptr
        ? nullptr
        : &std::get<TextSession>(*format_session);

    if (TextUndo* change = std::get_if<TextUndo>(&undo)) {
        swap_text_undo(data, session, *change, soft_wrap);
    } else if (TextStyleUndo* change =
                   std::get_if<TextStyleUndo>(&undo);
               supports_style_undo && change != nullptr) {
        swap_text_style_undo(data, *change);
    } else {
        swap_text_layout_undo(
            data,
            session,
            std::get<TextLayoutUndo>(undo),
            soft_wrap
        );
    }
}

FormatAction resize_text_card(
    FormatContext& context,
    const InputEvent& event,
    bool soft_wrap
) {
    TextCardData& data = std::get<TextCardData>(context.data);
    Extent next;

    if (!step_layout(
            event,
            data.layout,
            context.minimum_layout,
            context.maximum_layout,
            next
        )) {
        return {};
    }

    if (next == data.layout) {
        return view_action();
    }

    TextLayoutUndo undo{data.layout};
    data.layout = next;

    TextSession& session = std::get<TextSession>(context.session);
    keep_text_cursor_visible(data, session, soft_wrap);
    return stored_layout_action(FormatUndo{undo});
}

static bool move_wrapped_text_cursor(
    const TextCardData& data,
    TextSession& session,
    i32 direction,
    bool extend_selection
) {
    const i32 inner_width = data.layout.width - 2;
    TextVisualLine visual = wrapped_text_cursor_line(
        data,
        session,
        inner_width
    );
    const bool moved = direction < 0
        ? previous_wrapped_text_line(data, visual, inner_width)
        : next_wrapped_text_line(data, visual, inner_width);

    if (!moved) {
        return false;
    }

    const u32 byte = wrapped_text_byte_at_cell(
        data,
        visual,
        session.preferred_cell
    );
    set_text_cursor(
        data,
        session,
        TextPos{visual.row, byte},
        true,
        extend_selection,
        false,
        byte == visual.end_byte &&
            visual.end_byte < data.lines[visual.row].size()
    );
    return true;
}

FormatAction handle_text_input(
    FormatContext& context,
    const InputEvent& event,
    bool soft_wrap
) {
    TextCardData& data = std::get<TextCardData>(context.data);
    TextSession& session = std::get<TextSession>(context.session);

    switch (event.key) {
        case Key::Text:
        case Key::Paste:
            return replace_text_action(
                data,
                session,
                session.selection(),
                event.text,
                soft_wrap
            );

        case Key::Enter:
            return replace_text_action(
                data,
                session,
                session.selection(),
                "\n",
                soft_wrap
            );

        case Key::Tab:
            return replace_text_action(
                data,
                session,
                session.selection(),
                "\t",
                soft_wrap
            );

        case Key::Backspace: {
            TextRange range = session.selection();

            if (range.begin != range.end) {
                return replace_text_action(
                    data,
                    session,
                    range,
                    {},
                    soft_wrap
                );
            }

            const TextPos end = session.cursor;

            if (end.byte > 0) {
                range.begin = {
                    end.row,
                    previous_text_cluster_byte(
                        data.lines[end.row],
                        end.byte
                    )
                };
            } else if (end.row > 0) {
                range.begin = {
                    end.row - 1,
                    static_cast<u32>(data.lines[end.row - 1].size())
                };
            } else {
                return view_action();
            }

            range.end = end;
            return replace_text_action(
                data,
                session,
                range,
                {},
                soft_wrap
            );
        }

        case Key::Delete: {
            TextRange range = session.selection();

            if (range.begin != range.end) {
                return replace_text_action(
                    data,
                    session,
                    range,
                    {},
                    soft_wrap
                );
            }

            const TextPos begin = session.cursor;
            const std::string& line = data.lines[begin.row];

            if (begin.byte < line.size()) {
                range.end = {
                    begin.row,
                    next_text_cluster_byte(line, begin.byte)
                };
            } else if (begin.row + 1 < data.lines.size()) {
                range.end = {begin.row + 1, 0};
            } else {
                return view_action();
            }

            range.begin = begin;
            return replace_text_action(
                data,
                session,
                range,
                {},
                soft_wrap
            );
        }

        case Key::Left: {
            const TextRange selection = session.selection();

            if (!event.shift && selection.begin != selection.end) {
                set_text_cursor(
                    data,
                    session,
                    selection.begin,
                    soft_wrap,
                    false,
                    true
                );
                return view_action();
            }

            TextPos position = session.cursor;

            if (position.byte > 0) {
                position.byte = previous_text_cluster_byte(
                    data.lines[position.row],
                    position.byte
                );
            } else if (position.row > 0) {
                --position.row;
                position.byte = static_cast<u32>(
                    data.lines[position.row].size()
                );
            }

            set_text_cursor(
                data,
                session,
                position,
                soft_wrap,
                event.shift,
                true
            );
            return view_action();
        }

        case Key::Right: {
            const TextRange selection = session.selection();

            if (!event.shift && selection.begin != selection.end) {
                set_text_cursor(
                    data,
                    session,
                    selection.end,
                    soft_wrap,
                    false,
                    true
                );
                return view_action();
            }

            TextPos position = session.cursor;
            const std::string& line = data.lines[position.row];

            if (position.byte < line.size()) {
                position.byte = next_text_cluster_byte(
                    line,
                    position.byte
                );
            } else if (position.row + 1 < data.lines.size()) {
                ++position.row;
                position.byte = 0;
            }

            set_text_cursor(
                data,
                session,
                position,
                soft_wrap,
                event.shift,
                true
            );
            return view_action();
        }

        case Key::Up:
        case Key::Down: {
            if (soft_wrap) {
                move_wrapped_text_cursor(
                    data,
                    session,
                    event.key == Key::Up ? -1 : 1,
                    event.shift
                );
                return view_action();
            }

            u32 row = session.cursor.row;

            if (event.key == Key::Up) {
                if (row == 0) {
                    return view_action();
                }
                --row;
            } else {
                if (row + 1 >= data.lines.size()) {
                    return view_action();
                }
                ++row;
            }

            set_text_cursor(
                data,
                session,
                TextPos{
                    row,
                    byte_at_cell(
                        data.lines[row],
                        session.preferred_cell
                    )
                },
                false,
                event.shift,
                false
            );
            return view_action();
        }

        case Key::Home:
            set_text_cursor(
                data,
                session,
                TextPos{session.cursor.row, 0},
                soft_wrap,
                event.shift,
                true
            );
            return view_action();

        case Key::End:
            set_text_cursor(
                data,
                session,
                TextPos{
                    session.cursor.row,
                    static_cast<u32>(
                        data.lines[session.cursor.row].size()
                    )
                },
                soft_wrap,
                event.shift,
                true
            );
            return view_action();

        case Key::PageUp:
        case Key::PageDown: {
            const i32 direction =
                event.key == Key::PageUp ? -1 : 1;
            const i32 count = data.layout.height - 2;

            if (soft_wrap) {
                TextVisualLine visual = wrapped_text_cursor_line(
                    data,
                    session,
                    data.layout.width - 2
                );

                if (direction < 0) {
                    previous_wrapped_text_lines(
                        data,
                        visual,
                        data.layout.width - 2,
                        static_cast<u32>(count)
                    );
                } else {
                    for (i32 i = 0; i < count; ++i) {
                        const bool moved = next_wrapped_text_line(
                            data,
                            visual,
                            data.layout.width - 2
                        );

                        if (!moved) {
                            break;
                        }
                    }
                }

                const u32 byte = wrapped_text_byte_at_cell(
                    data,
                    visual,
                    session.preferred_cell
                );
                set_text_cursor(
                    data,
                    session,
                    {visual.row, byte},
                    true,
                    event.shift,
                    false,
                    byte == visual.end_byte &&
                        visual.end_byte < data.lines[visual.row].size()
                );
                return view_action();
            }

            const u32 last = static_cast<u32>(data.lines.size() - 1);
            const u32 row = direction < 0
                ? session.cursor.row > static_cast<u32>(count)
                    ? session.cursor.row - static_cast<u32>(count)
                    : 0
                : std::min(
                    last,
                    session.cursor.row + static_cast<u32>(count)
                );
            set_text_cursor(
                data,
                session,
                {
                    row,
                    byte_at_cell(
                        data.lines[row],
                        session.preferred_cell
                    )
                },
                false,
                event.shift,
                false
            );
            return view_action();
        }

        case Key::CtrlA: {
            const u32 row = static_cast<u32>(data.lines.size() - 1);
            session.selection_anchor = {0, 0};
            set_text_cursor(
                data,
                session,
                TextPos{
                    row,
                    static_cast<u32>(data.lines[row].size())
                },
                soft_wrap,
                true,
                true
            );
            return view_action();
        }

        case Key::CtrlC: {
            const TextRange range = session.selection();

            if (range.begin != range.end) {
                context.clipboard = extract_text(data.lines, range);
            }
            return view_action();
        }

        case Key::CtrlX: {
            const TextRange range = session.selection();

            if (range.begin == range.end) {
                return view_action();
            }

            std::string selected = extract_text(data.lines, range);
            context.clipboard = selected;
            return replace_text_action(
                data,
                session,
                range,
                {},
                soft_wrap,
                std::move(selected)
            );
        }

        case Key::CtrlV: {
            const std::string* text =
                std::get_if<std::string>(&context.clipboard);

            return text == nullptr
                ? view_action()
                : replace_text_action(
                    data,
                    session,
                    session.selection(),
                    *text,
                    soft_wrap
                );
        }

        default:
            return {};
    }
}

FormatAction handle_text_card_input(
    FormatContext& context,
    const InputEvent& event,
    bool soft_wrap,
    TextSpecialInputFunction control_b
) {
    FormatAction action = resize_text_card(
        context,
        event,
        soft_wrap
    );

    if (action.handled) {
        return action;
    }

    if (event.key == Key::CtrlB && control_b != nullptr) {
        return control_b(context);
    }

    return handle_text_input(context, event, soft_wrap);
}
