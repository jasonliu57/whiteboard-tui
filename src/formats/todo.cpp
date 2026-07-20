#include "registry.hpp"
#include "draw.hpp"

static Style default_todo_style(const TodoItem& item) {
    return item.done
        ? Style{2, 0, AttrNone}
        : Style{7, 0, AttrNone};
}

static void append_todo_text(
    std::string& destination,
    std::string_view text
) {
    destination.reserve(destination.size() + text.size());

    for (char ch : text) {
        destination.push_back(ch == '\n' ? ' ' : ch);
    }
}

static void rebuild_todo(CardData& card_data) {
    TodoCardData& data = std::get<TodoCardData>(card_data);

    if (data.items.empty()) {
        data.items.emplace_back();
    }

    for (TodoItem& item : data.items) {
        item.style = canonical_style(item.style);
    }
}

static Extent measure_todo(const CardData& data) {
    return std::get<TodoCardData>(data).layout;
}

static void begin_todo(
    FormatSession& session,
    const CardData&
) {
    session = TodoSession{};
}

static void keep_todo_visible(
    const TodoCardData& data,
    TodoSession& session
) {
    if (session.selected_item >= data.items.size()) {
        session.selected_item =
            static_cast<u32>(data.items.size() - 1);
    }

    const u32 visible = static_cast<u32>(data.layout.height - 2);

    if (session.selected_item < session.scroll_item) {
        session.scroll_item = session.selected_item;
    } else if (
        session.selected_item >= session.scroll_item + visible
    ) {
        session.scroll_item =
            session.selected_item - visible + 1;
    }
}

static void draw_todo(
    Screen& screen,
    const CardData& card_data,
    CardId id,
    i32 x,
    i32 y,
    const CardFormat& format,
    CardVisualState visual_state,
    const FormatSession* active_session
) {
    const TodoCardData& data = std::get<TodoCardData>(card_data);
    const TodoSession* session =
        active_session == nullptr
            ? nullptr
            : &std::get<TodoSession>(*active_session);

    draw_box(
        screen,
        data.layout,
        id,
        x,
        y,
        format,
        visual_state
    );

    const i32 inner_width = data.layout.width - 2;
    const i32 inner_height = data.layout.height - 2;
    const u32 scroll = session == nullptr ? 0 : session->scroll_item;
    const VisibleRowRange rows = visible_rows(
        screen,
        y + 1,
        inner_height
    );

    for (i32 local_row = rows.first;
         local_row < rows.last;
         ++local_row) {
        const u32 row = scroll + static_cast<u32>(local_row);

        if (row >= data.items.size()) {
            break;
        }

        const TodoItem& item = data.items[row];
        draw_string(
            screen,
            x + 1,
            y + 1 + local_row,
            inner_width,
            item.done ? "[x] " : "[ ] ",
            item.style,
            id
        );

        if (inner_width > 4) {
            draw_string(
                screen,
                x + 5,
                y + 1 + local_row,
                inner_width - 4,
                item.text,
                item.style,
                id
            );
        }

        if (session != nullptr && row == session->selected_item) {
            screen.invert_span(
                x + 1,
                y + 1 + local_row,
                inner_width,
                id
            );
        }
    }
}

static FormatAction resize_todo(
    FormatContext& context,
    const InputEvent& event
) {
    TodoCardData& data = std::get<TodoCardData>(context.data);
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

    TodoLayoutUndo undo{};
    undo.layout = data.layout;
    data.layout = next;
    keep_todo_visible(data, std::get<TodoSession>(context.session));
    return stored_layout_action(FormatUndo{std::move(undo)});
}

static FormatAction input_todo(
    FormatContext& context,
    const InputEvent& event
) {
    FormatAction action = resize_todo(context, event);

    if (action.handled) {
        return action;
    }

    TodoCardData& data = std::get<TodoCardData>(context.data);
    TodoSession& session = std::get<TodoSession>(context.session);

    switch (event.key) {
        case Key::Up:
            if (session.selected_item > 0) {
                --session.selected_item;
            }
            keep_todo_visible(data, session);
            return view_action();

        case Key::Down:
            if (session.selected_item + 1 < data.items.size()) {
                ++session.selected_item;
            }
            keep_todo_visible(data, session);
            return view_action();

        case Key::Home:
            session.selected_item = 0;
            keep_todo_visible(data, session);
            return view_action();

        case Key::End:
            session.selected_item =
                static_cast<u32>(data.items.size() - 1);
            keep_todo_visible(data, session);
            return view_action();

        case Key::Tab: {
            TodoItem& item = data.items[session.selected_item];
            TodoToggleUndo undo{};
            undo.index = session.selected_item;
            undo.done = item.done;
            undo.style = item.style;
            item.done = !item.done;
            item.style = default_todo_style(item);
            return stored_action(FormatUndo{std::move(undo)});
        }

        case Key::Enter: {
            const u32 previous = session.selected_item;
            const u32 inserted = previous + 1;
            TodoItemUndo undo{};
            undo.index = inserted;
            undo.item_present = false;
            undo.current_selection = inserted;
            undo.replacement_selection = previous;
            const auto position = data.items.begin() + inserted;
            data.items.insert(position, TodoItem{});
            session.selected_item = inserted;
            keep_todo_visible(data, session);
            return stored_action(FormatUndo{std::move(undo)});
        }

        case Key::Delete:
        case Key::CtrlX: {
            if (data.items.size() == 1) {
                TodoReplaceItemUndo undo{};
                undo.index = 0;
                undo.item = std::move(data.items[0]);
                data.items[0] = {};
                return stored_action(FormatUndo{std::move(undo)});
            } else {
                const u32 erased = session.selected_item;
                const u32 next = std::min<u32>(
                    erased,
                    static_cast<u32>(data.items.size() - 2)
                );
                TodoItemUndo undo{};
                undo.index = erased;
                undo.item = std::move(data.items[erased]);
                undo.item_present = true;
                undo.current_selection = next;
                undo.replacement_selection = erased;
                data.items.erase(
                    data.items.begin() + erased
                );
                session.selected_item = next;
                keep_todo_visible(data, session);
                return stored_action(FormatUndo{std::move(undo)});
            }
        }

        case Key::Backspace: {
            std::string& text = data.items[session.selected_item].text;

            if (text.empty()) {
                return view_action();
            }

            const u32 begin = previous_utf8_byte(
                text,
                static_cast<u32>(text.size())
            );
            TodoTextUndo undo{};
            undo.index = session.selected_item;
            undo.begin_byte = begin;
            undo.end_byte = begin;
            undo.text = text.substr(begin);
            text.erase(begin);
            return stored_action(FormatUndo{std::move(undo)});
        }

        case Key::CtrlB: {
            Style& style = data.items[session.selected_item].style;
            TodoStyleUndo undo{};
            undo.index = session.selected_item;
            undo.style = style;
            style.foreground = static_cast<u8>(
                style.foreground >= 6 ? 1 : style.foreground + 1
            );
            return stored_action(FormatUndo{std::move(undo)});
        }

        case Key::CtrlC:
            context.clipboard = data.items[session.selected_item].text;
            return view_action();

        case Key::CtrlV: {
            const std::string* text =
                std::get_if<std::string>(&context.clipboard);

            if (text == nullptr) {
                return view_action();
            }

            std::string& destination =
                data.items[session.selected_item].text;
            const u32 begin = static_cast<u32>(destination.size());
            append_todo_text(
                destination,
                *text
            );
            const u32 end = static_cast<u32>(destination.size());

            if (begin == end) {
                return view_action();
            }

            TodoTextUndo undo{};
            undo.index = session.selected_item;
            undo.begin_byte = begin;
            undo.end_byte = end;
            return stored_action(FormatUndo{std::move(undo)});
        }

        case Key::Text:
        case Key::Paste: {
            std::string& destination =
                data.items[session.selected_item].text;
            const u32 begin = static_cast<u32>(destination.size());
            append_todo_text(
                destination,
                event.text
            );
            const u32 end = static_cast<u32>(destination.size());

            if (begin == end) {
                return view_action();
            }

            TodoTextUndo undo{};
            undo.index = session.selected_item;
            undo.begin_byte = begin;
            undo.end_byte = end;
            return stored_action(FormatUndo{std::move(undo)});
        }

        default:
            return {};
    }
}

static void swap_todo_undo(
    CardData& card_data,
    FormatSession* format_session,
    FormatUndo& undo
) {
    TodoCardData& data = std::get<TodoCardData>(card_data);
    TodoSession* session = format_session == nullptr
        ? nullptr
        : &std::get<TodoSession>(*format_session);

    if (auto* change = std::get_if<TodoLayoutUndo>(&undo)) {
        std::swap(data.layout, change->layout);
    } else if (auto* change = std::get_if<TodoToggleUndo>(&undo)) {
        std::swap(data.items[change->index].done, change->done);
        std::swap(data.items[change->index].style, change->style);
    } else if (auto* change = std::get_if<TodoTextUndo>(&undo)) {
        std::string& text = data.items[change->index].text;
        std::string current = text.substr(
            change->begin_byte,
            change->end_byte - change->begin_byte
        );
        text.replace(
            change->begin_byte,
            change->end_byte - change->begin_byte,
            change->text
        );
        change->end_byte = change->begin_byte +
            static_cast<u32>(change->text.size());
        change->text = std::move(current);
    } else if (auto* change = std::get_if<TodoItemUndo>(&undo)) {
        if (change->item_present) {
            data.items.insert(
                data.items.begin() + change->index,
                std::move(change->item)
            );
            change->item_present = false;
        } else {
            change->item = std::move(data.items[change->index]);
            data.items.erase(data.items.begin() + change->index);
            change->item_present = true;
        }

        if (session != nullptr) {
            session->selected_item = change->replacement_selection;
        }

        std::swap(
            change->current_selection,
            change->replacement_selection
        );
    } else if (auto* change =
                   std::get_if<TodoReplaceItemUndo>(&undo)) {
        std::swap(data.items[change->index], change->item);
    } else if (auto* change = std::get_if<TodoStyleUndo>(&undo)) {
        std::swap(data.items[change->index].style, change->style);
    }

    if (session != nullptr) {
        keep_todo_visible(data, *session);
    }
}

CardFormat make_todo_format() {
    CardFormat format;
    format.name = "todo";
    format.data_kind = CardDataKind::Todo;
    apply_generated_card_format_contract(format, kCardFormatTodo);
    format.border = Style{2, 0, AttrBold};
    format.body = Style{7, 0, AttrNone};
    format.title = Style{2, 0, AttrBold};
    format.active_border = Style{3, 0, AttrBold};
    format.measure = measure_todo;
    format.draw = draw_todo;
    format.begin = begin_todo;
    format.input = input_todo;
    format.rebuild = rebuild_todo;
    format.swap_undo = swap_todo_undo;
    format.create_empty = make_todo_card;
    return format;
}

Card make_todo_card(
    Pos pos,
    i32 width,
    i32 height
) {
    TodoCardData data;
    data.layout = {width, height};

    Card card;
    card.pos = pos;
    card.static_format = kTodoStaticFormatId;
    card.data = std::move(data);
    return card;
}
