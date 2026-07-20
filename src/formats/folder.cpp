#include "registry.hpp"
#include "draw.hpp"

#include <iterator>

static void rebuild_folder(CardData& card_data) {
    FolderCardData& data = std::get<FolderCardData>(card_data);

    for (u32 i = 0; i < data.entries.size(); ++i) {
        FolderEntry& entry = data.entries[i];

        if (entry.kind == FolderEntryKind::Directory) {
            entry.target = kNoCard;
        } else {
            entry.collapsed = false;
        }

        if (i == 0) {
            entry.depth = 0;
            continue;
        }

        const FolderEntry& previous = data.entries[i - 1];
        const u32 deepest =
            previous.depth +
            (previous.kind == FolderEntryKind::Directory ? 1 : 0);
        entry.depth = std::min(entry.depth, deepest);
    }
}

static Extent measure_folder(const CardData& data) {
    return std::get<FolderCardData>(data).layout;
}

static void begin_folder(
    FormatSession& session,
    const CardData&
) {
    session = FolderSession{};
}

struct FolderVisibleCursor {
    const FolderCardData& data;
    u32 entry = kNoFolderEntry;
    u32 row = 0;
    u32 next_entry = 0;
    u32 hidden_depth = kNoFolderEntry;

    explicit FolderVisibleCursor(const FolderCardData& value)
        : data(value) {}

    bool next() {
        while (next_entry < data.entries.size()) {
            const u32 index = next_entry++;
            const FolderEntry& candidate = data.entries[index];

            if (hidden_depth != kNoFolderEntry) {
                if (candidate.depth > hidden_depth) {
                    continue;
                }

                hidden_depth = kNoFolderEntry;
            }

            entry = index;
            ++row;

            if (
                candidate.kind == FolderEntryKind::Directory &&
                candidate.collapsed
            ) {
                hidden_depth = candidate.depth;
            }
            return true;
        }

        return false;
    }
};

static u32 folder_neighbor(
    const FolderCardData& data,
    u32 selected,
    bool forward
) {
    FolderVisibleCursor cursor(data);
    u32 previous = kNoFolderEntry;
    bool found = false;

    do {
        if (forward) {
            if (found) {
                return cursor.entry;
            }

            if (cursor.entry == selected) {
                found = true;
            }
        } else if (cursor.entry == selected) {
            return previous;
        }

        previous = cursor.entry;
    } while (cursor.next());

    return kNoFolderEntry;
}

static u32 folder_last_visible(const FolderCardData& data) {
    FolderVisibleCursor cursor(data);
    u32 last = kNoFolderEntry;

    while (cursor.next()) {
        last = cursor.entry;
    }

    return last;
}

static bool folder_entry_visible(
    const FolderCardData& data,
    u32 target
) {
    FolderVisibleCursor cursor(data);

    do {
        if (cursor.entry == target) {
            return true;
        }
    } while (cursor.next());

    return false;
}

static u32 folder_selected_row(
    const FolderCardData& data,
    u32 selected
) {
    if (selected == kNoFolderEntry) {
        return 0;
    }

    FolderVisibleCursor cursor(data);

    while (cursor.next()) {
        if (cursor.entry == selected) {
            return cursor.row;
        }
    }

    return 0;
}

static void keep_folder_visible(
    const FolderCardData& data,
    FolderSession& session
) {
    const u32 row = folder_selected_row(
        data,
        session.selected_entry
    );
    const u32 visible = static_cast<u32>(data.layout.height - 2);

    if (row < session.scroll_row) {
        session.scroll_row = row;
    } else if (row >= session.scroll_row + visible) {
        session.scroll_row = row - visible + 1;
    }
}

static u32 folder_subtree_end(
    const FolderCardData& data,
    u32 begin
) {
    u32 end = begin + 1;

    while (
        end < data.entries.size() &&
        data.entries[end].depth > data.entries[begin].depth
    ) {
        ++end;
    }

    return end;
}

static u32 folder_parent(
    const FolderCardData& data,
    u32 child
) {
    const u32 depth = data.entries[child].depth;

    if (depth == 0) {
        return kNoFolderEntry;
    }

    for (u32 i = child; i > 0;) {
        --i;

        if (data.entries[i].depth < depth) {
            return i;
        }
    }

    return kNoFolderEntry;
}

static u32 folder_previous_sibling_directory(
    const FolderCardData& data,
    u32 selected
) {
    const u32 depth = data.entries[selected].depth;

    for (u32 i = selected; i > 0;) {
        --i;

        if (data.entries[i].depth < depth) {
            break;
        }

        if (data.entries[i].depth == depth) {
            return
                data.entries[i].kind == FolderEntryKind::Directory
                    ? i
                    : kNoFolderEntry;
        }
    }

    return kNoFolderEntry;
}

static u32 folder_insert_position(
    const FolderCardData& data,
    u32 selected
) {
    return selected == kNoFolderEntry
        ? static_cast<u32>(data.entries.size())
        : folder_subtree_end(data, selected);
}

static u32 folder_insert_depth(
    const FolderCardData& data,
    u32 selected
) {
    return selected == kNoFolderEntry
        ? 0
        : data.entries[selected].depth;
}

static bool append_folder_name(
    std::string& name,
    std::string_view text
) {
    const std::size_t previous = name.size();
    name.reserve(previous + text.size());

    for (char ch : text) {
        if (ch != '\0' && ch != '\n' && ch != '\r' && ch != '/') {
            name.push_back(ch);
        }
    }

    return name.size() != previous;
}

static std::string& selected_folder_name(
    FolderCardData& data,
    const FolderSession& session
) {
    return session.selected_entry == kNoFolderEntry
        ? data.name
        : data.entries[session.selected_entry].name;
}

static void draw_folder(
    Screen& screen,
    const CardData& card_data,
    CardId id,
    i32 x,
    i32 y,
    const CardFormat& format,
    CardVisualState visual_state,
    const FormatSession* active_session
) {
    const FolderCardData& data =
        std::get<FolderCardData>(card_data);
    const FolderSession* session =
        active_session == nullptr
            ? nullptr
            : &std::get<FolderSession>(*active_session);

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
    const u32 scroll = session == nullptr ? 0 : session->scroll_row;
    const VisibleRowRange rows = visible_rows(
        screen,
        y + 1,
        inner_height
    );
    const u32 first = scroll + static_cast<u32>(rows.first);
    const u32 bottom = scroll + static_cast<u32>(rows.last);
    FolderVisibleCursor cursor(data);

    do {
        if (cursor.row >= bottom) {
            break;
        }

        if (cursor.row < first) {
            continue;
        }

        Style style = format.title;
        i32 cell = 0;
        std::string_view prefix;
        std::string_view name;
        bool directory = true;

        if (cursor.entry == kNoFolderEntry) {
            prefix = "▾ ";
            name = data.name.empty()
                ? std::string_view{"folder"}
                : std::string_view{data.name};
        } else {
            const FolderEntry& entry = data.entries[cursor.entry];
            cell = std::min<i32>(
                inner_width,
                static_cast<i32>(std::min<u32>(
                    entry.depth,
                    static_cast<u32>(inner_width / 2)
                ) * 2)
            );
            directory = entry.kind == FolderEntryKind::Directory;

            if (directory) {
                prefix = entry.collapsed ? "▸ " : "▾ ";
                name = entry.name.empty()
                    ? std::string_view{"folder"}
                    : std::string_view{entry.name};
            } else {
                prefix = "· ";
                name = entry.name.empty()
                    ? std::string_view{"card"}
                    : std::string_view{entry.name};
                style = format.body;
            }
        }

        const i32 screen_y = y + 1 + static_cast<i32>(
            cursor.row - scroll
        );
        cell += draw_string(
            screen,
            x + 1 + cell,
            screen_y,
            inner_width - cell,
            prefix,
            style,
            id
        );
        cell += draw_string(
            screen,
            x + 1 + cell,
            screen_y,
            inner_width - cell,
            name,
            style,
            id
        );

        if (directory) {
            draw_string(
                screen,
                x + 1 + cell,
                screen_y,
                inner_width - cell,
                "/",
                style,
                id
            );
        }

        if (
            session != nullptr &&
            cursor.entry == session->selected_entry
        ) {
            screen.invert_span(
                x + 1,
                screen_y,
                inner_width,
                id
            );
        }
    } while (cursor.next());

    if (
        data.entries.empty() &&
        first <= 1 &&
        1 < bottom
    ) {
        draw_string(
            screen,
            x + 1,
            y + 1 + static_cast<i32>(1 - scroll),
            inner_width,
            "  (empty)",
            format.body,
            id
        );
    }
}

static FormatAction resize_folder(
    FormatContext& context,
    const InputEvent& event
) {
    FolderCardData& data =
        std::get<FolderCardData>(context.data);
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

    FolderSession& session =
        std::get<FolderSession>(context.session);
    FolderLayoutUndo undo{};
    undo.layout = data.layout;
    data.layout = next;
    keep_folder_visible(data, session);
    return stored_layout_action(FormatUndo{std::move(undo)});
}

static FormatAction input_folder(
    FormatContext& context,
    const InputEvent& event
) {
    FormatAction action = resize_folder(context, event);

    if (action.handled) {
        return action;
    }

    FolderCardData& data =
        std::get<FolderCardData>(context.data);
    FolderSession& session =
        std::get<FolderSession>(context.session);

    switch (event.key) {
        case Key::Up:
            session.selected_entry = folder_neighbor(
                data,
                session.selected_entry,
                false
            );
            keep_folder_visible(data, session);
            return view_action();

        case Key::Down: {
            const u32 next = folder_neighbor(
                data,
                session.selected_entry,
                true
            );

            if (next != kNoFolderEntry) {
                session.selected_entry = next;
            }

            keep_folder_visible(data, session);
            return view_action();
        }

        case Key::Left:
            if (session.selected_entry == kNoFolderEntry) {
                return view_action();
            }

            if (
                data.entries[session.selected_entry].kind ==
                    FolderEntryKind::Directory &&
                !data.entries[session.selected_entry].collapsed
            ) {
                FolderCollapseUndo undo{};
                undo.entry = session.selected_entry;
                undo.collapsed = false;
                data.entries[session.selected_entry].collapsed = true;
                return stored_action(FormatUndo{std::move(undo)});
            }

            session.selected_entry = folder_parent(
                data,
                session.selected_entry
            );
            keep_folder_visible(data, session);
            return view_action();

        case Key::Right:
            if (session.selected_entry == kNoFolderEntry) {
                session.selected_entry = folder_neighbor(
                    data,
                    session.selected_entry,
                    true
                );
                keep_folder_visible(data, session);
                return view_action();
            }

            if (
                data.entries[session.selected_entry].kind !=
                    FolderEntryKind::Directory
            ) {
                return view_action();
            }

            if (data.entries[session.selected_entry].collapsed) {
                FolderCollapseUndo undo{};
                undo.entry = session.selected_entry;
                undo.collapsed = true;
                data.entries[session.selected_entry].collapsed = false;
                return stored_action(FormatUndo{std::move(undo)});
            }

            if (
                session.selected_entry + 1 < data.entries.size() &&
                data.entries[session.selected_entry + 1].depth >
                    data.entries[session.selected_entry].depth
            ) {
                ++session.selected_entry;
                keep_folder_visible(data, session);
            }
            return view_action();

        case Key::Enter:
            if (session.selected_entry == kNoFolderEntry) {
                return view_action();
            }

            if (
                data.entries[session.selected_entry].kind ==
                    FolderEntryKind::Directory
            ) {
                FolderEntry& entry = data.entries[session.selected_entry];
                FolderCollapseUndo undo{};
                undo.entry = session.selected_entry;
                undo.collapsed = entry.collapsed;
                entry.collapsed = !entry.collapsed;
                return stored_action(FormatUndo{std::move(undo)});
            } else {
                FormatAction focus = view_action();
                focus.focus_requested = true;
                focus.focus_card =
                    data.entries[session.selected_entry].target;
                return focus;
            }

        case Key::Home:
            session.selected_entry = kNoFolderEntry;
            keep_folder_visible(data, session);
            return view_action();

        case Key::End: {
            session.selected_entry = folder_last_visible(data);
            keep_folder_visible(data, session);
            return view_action();
        }

        case Key::CtrlA: {
            const u32 previous = session.selected_entry;
            const u32 position = folder_insert_position(
                data,
                session.selected_entry
            );
            const u32 depth = folder_insert_depth(
                data,
                session.selected_entry
            );
            FolderEntriesUndo undo{};
            undo.position = position;
            undo.count = 1;
            undo.entries_present = false;
            undo.current_selection = position;
            undo.replacement_selection = previous;
            data.entries.insert(
                data.entries.begin() + position,
                FolderEntry{
                    .kind = FolderEntryKind::Directory,
                    .depth = depth,
                    .name = {},
                    .target = kNoCard,
                    .collapsed = false,
                }
            );
            session.selected_entry = position;
            keep_folder_visible(data, session);
            return stored_action(FormatUndo{std::move(undo)});
        }

        case Key::Tab: {
            if (session.selected_entry == kNoFolderEntry) {
                return view_action();
            }

            const u32 begin = session.selected_entry;
            const u32 end = folder_subtree_end(data, begin);

            if (event.shift) {
                if (data.entries[begin].depth == 0) {
                    return view_action();
                }

                FolderOutdentUndo undo{};
                undo.replacement_selection = session.selected_entry;
                const u32 parent = folder_parent(data, begin);
                const u32 parent_end = folder_subtree_end(data, parent);
                const u32 size = end - begin;
                undo.position = begin;
                undo.count = size;
                undo.move_end = parent_end;
                undo.outdented = true;
                std::rotate(
                    data.entries.begin() + begin,
                    data.entries.begin() + end,
                    data.entries.begin() + parent_end
                );
                const u32 moved = parent_end - size;

                for (u32 i = moved; i < parent_end; ++i) {
                    --data.entries[i].depth;
                }

                session.selected_entry = moved;
                undo.current_selection = moved;
                keep_folder_visible(data, session);
                return stored_action(FormatUndo{std::move(undo)});
            }

            const u32 parent = folder_previous_sibling_directory(
                data,
                begin
            );

            if (parent == kNoFolderEntry) {
                return view_action();
            }

            FolderIndentUndo undo{};
            undo.position = begin;
            undo.count = end - begin;
            undo.entry = parent;
            undo.collapsed = data.entries[parent].collapsed;
            undo.depth_delta = -1;
            data.entries[parent].collapsed = false;

            for (u32 i = begin; i < end; ++i) {
                ++data.entries[i].depth;
            }

            keep_folder_visible(data, session);
            return stored_action(FormatUndo{std::move(undo)});
        }

        case Key::Delete:
        case Key::CtrlX: {
            if (session.selected_entry == kNoFolderEntry) {
                return view_action();
            }

            const u32 begin = session.selected_entry;
            const u32 end = folder_subtree_end(data, begin);
            const u32 next = folder_neighbor(data, begin, false);
            FolderEntriesUndo undo{};
            undo.position = begin;
            undo.count = end - begin;
            undo.entries_present = true;
            undo.entries.reserve(undo.count);

            for (u32 i = begin; i < end; ++i) {
                undo.entries.push_back(std::move(data.entries[i]));
            }

            undo.current_selection = next;
            undo.replacement_selection = begin;
            session.selected_entry = next;
            data.entries.erase(
                data.entries.begin() + begin,
                data.entries.begin() + end
            );
            keep_folder_visible(data, session);
            return stored_action(FormatUndo{std::move(undo)});
        }

        case Key::CtrlC:
            context.clipboard = selected_folder_name(data, session);
            return view_action();

        case Key::CtrlV: {
            if (const auto* copy =
                    std::get_if<CardClipboard>(&context.clipboard)) {
                const u32 previous = session.selected_entry;
                const u32 position = folder_insert_position(
                    data,
                    session.selected_entry
                );
                const u32 depth = folder_insert_depth(
                    data,
                    session.selected_entry
                );
                FolderEntriesUndo undo{};
                undo.position = position;
                undo.count = 1;
                undo.entries_present = false;
                undo.current_selection = position;
                undo.replacement_selection = previous;
                data.entries.insert(
                    data.entries.begin() + position,
                    FolderEntry{
                        .kind = FolderEntryKind::Card,
                        .depth = depth,
                        .name = copy->name,
                        .target = copy->source,
                    }
                );
                session.selected_entry = position;
                keep_folder_visible(data, session);
                return stored_action(FormatUndo{std::move(undo)});
            }

            const auto* text =
                std::get_if<std::string>(&context.clipboard);

            if (text == nullptr) {
                return view_action();
            }

            std::string& name = selected_folder_name(data, session);
            const u32 begin = static_cast<u32>(name.size());

            if (!append_folder_name(name, *text)) {
                return view_action();
            }

            FolderRenameUndo undo{};
            undo.entry = session.selected_entry;
            undo.begin_byte = begin;
            undo.end_byte = static_cast<u32>(name.size());
            return stored_action(FormatUndo{std::move(undo)});
        }

        case Key::Backspace: {
            std::string& name = selected_folder_name(data, session);

            if (name.empty()) {
                return view_action();
            }

            const u32 begin = previous_utf8_byte(
                name,
                static_cast<u32>(name.size())
            );
            FolderRenameUndo undo{};
            undo.entry = session.selected_entry;
            undo.begin_byte = begin;
            undo.end_byte = begin;
            undo.text = name.substr(begin);
            name.erase(begin);
            return stored_action(FormatUndo{std::move(undo)});
        }

        case Key::Text:
        case Key::Paste: {
            std::string& name = selected_folder_name(data, session);
            const u32 begin = static_cast<u32>(name.size());

            if (!append_folder_name(name, event.text)) {
                return view_action();
            }

            FolderRenameUndo undo{};
            undo.entry = session.selected_entry;
            undo.begin_byte = begin;
            undo.end_byte = static_cast<u32>(name.size());
            return stored_action(FormatUndo{std::move(undo)});
        }

        default:
            return {};
    }
}

static void swap_folder_undo(
    CardData& card_data,
    FormatSession* format_session,
    FormatUndo& undo
) {
    FolderCardData& data = std::get<FolderCardData>(card_data);
    FolderSession* session = format_session == nullptr
        ? nullptr
        : &std::get<FolderSession>(*format_session);

    if (auto* change = std::get_if<FolderLayoutUndo>(&undo)) {
        std::swap(data.layout, change->layout);
    } else if (auto* change = std::get_if<FolderRenameUndo>(&undo)) {
        std::string& name = change->entry == kNoFolderEntry
            ? data.name
            : data.entries[change->entry].name;
        std::string current = name.substr(
            change->begin_byte,
            change->end_byte - change->begin_byte
        );
        name.replace(
            change->begin_byte,
            change->end_byte - change->begin_byte,
            change->text
        );
        change->end_byte = change->begin_byte +
            static_cast<u32>(change->text.size());
        change->text = std::move(current);
    } else if (auto* change = std::get_if<FolderCollapseUndo>(&undo)) {
        std::swap(
            data.entries[change->entry].collapsed,
            change->collapsed
        );
    } else if (auto* change = std::get_if<FolderEntriesUndo>(&undo)) {
        if (change->entries_present) {
            data.entries.insert(
                data.entries.begin() + change->position,
                std::make_move_iterator(change->entries.begin()),
                std::make_move_iterator(change->entries.end())
            );
            change->entries.clear();
            change->entries_present = false;
        } else {
            change->entries.reserve(change->count);

            for (u32 i = 0; i < change->count; ++i) {
                change->entries.push_back(std::move(
                    data.entries[change->position + i]
                ));
            }

            data.entries.erase(
                data.entries.begin() + change->position,
                data.entries.begin() + change->position + change->count
            );
            change->entries_present = true;
        }

        if (session != nullptr) {
            session->selected_entry = change->replacement_selection;
        }

        std::swap(
            change->current_selection,
            change->replacement_selection
        );
    } else if (auto* change = std::get_if<FolderIndentUndo>(&undo)) {
        std::swap(
            data.entries[change->entry].collapsed,
            change->collapsed
        );

        for (u32 i = change->position;
             i < change->position + change->count;
             ++i) {
            data.entries[i].depth = static_cast<u32>(
                static_cast<i32>(data.entries[i].depth) +
                change->depth_delta
            );
        }

        change->depth_delta = -change->depth_delta;
    } else if (auto* change = std::get_if<FolderOutdentUndo>(&undo)) {
        const u32 begin = change->position;
        const u32 end = begin + change->count;
        const u32 moved = change->move_end - change->count;

        if (change->outdented) {
            for (u32 i = moved; i < change->move_end; ++i) {
                ++data.entries[i].depth;
            }

            std::rotate(
                data.entries.begin() + begin,
                data.entries.begin() + moved,
                data.entries.begin() + change->move_end
            );
        } else {
            std::rotate(
                data.entries.begin() + begin,
                data.entries.begin() + end,
                data.entries.begin() + change->move_end
            );

            for (u32 i = moved; i < change->move_end; ++i) {
                --data.entries[i].depth;
            }
        }

        change->outdented = !change->outdented;

        if (session != nullptr) {
            session->selected_entry = change->replacement_selection;
        }

        std::swap(
            change->current_selection,
            change->replacement_selection
        );
    }

    if (session == nullptr) {
        return;
    }

    if (
        session->selected_entry != kNoFolderEntry &&
        (session->selected_entry >= data.entries.size() ||
         !folder_entry_visible(data, session->selected_entry))
    ) {
        session->selected_entry = kNoFolderEntry;
    }

    keep_folder_visible(data, *session);
}

CardFormat make_folder_format() {
    CardFormat format;
    format.name = "folder";
    format.data_kind = CardDataKind::Folder;
    apply_generated_card_format_contract(format, kCardFormatFolder);
    format.border = Style{3, 0, AttrBold};
    format.body = Style{7, 0, AttrNone};
    format.title = Style{6, 0, AttrBold};
    format.active_border = Style{3, 0, AttrBold};
    format.measure = measure_folder;
    format.draw = draw_folder;
    format.begin = begin_folder;
    format.input = input_folder;
    format.rebuild = rebuild_folder;
    format.swap_undo = swap_folder_undo;
    format.create_empty = make_folder_card;
    return format;
}

Card make_folder_card(
    Pos pos,
    i32 width,
    i32 height
) {
    FolderCardData data;
    data.layout = {width, height};

    Card card;
    card.pos = pos;
    card.static_format = kFolderStaticFormatId;
    card.data = std::move(data);
    return card;
}
