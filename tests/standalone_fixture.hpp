#pragma once

#include "../src/app.hpp"
#include <stdexcept>

inline void populate_standalone_fixture(App& app) {
    const auto require = [](bool value) {
        if (!value) throw std::runtime_error("invalid standalone test fixture");
    };
    Card note = make_plain_text_note({1, 2}, 12, 5);
    TextCardData& note_data = std::get<TextCardData>(note.data);
    note_data.lines = {"Title 中文 e\xCC\x81", "a\"\\\t"};
    note_data.styles = {
        RowStyles{1, TextSpan{1, 0, 2, Style{3, 4, AttrBold | AttrUnderline}}},
    };
    require(app.add_card(std::move(note)) == 0);

    Card markdown = make_markdown_card({20, 2}, 16, 6);
    std::get<TextCardData>(markdown.data).lines = {"# M"};
    require(app.add_card(std::move(markdown)) == 1);

    Card code = make_code_card({40, 2}, kCppLanguageId, 20, 7);
    std::get<TextCardData>(code.data).lines = {"int x;"};
    require(app.add_card(std::move(code)) == 2);

    Card todo = make_todo_card({65, 2}, 12, 5);
    TodoCardData& todo_data = std::get<TodoCardData>(todo.data);
    todo_data.items = {
        TodoItem{"done", true},
        TodoItem{"todo", false},
    };
    todo_data.items[0].style = {2, 1, AttrBold};
    require(app.add_card(std::move(todo)) == 3);

    Card csv = make_csv_card({85, 2}, 14, 5);
    CsvCardData& csv_data = std::get<CsvCardData>(csv.data);
    csv_data.cells = {{"a", "b\nc"}};
    csv_data.column_widths = {5, 9};
    csv_data.styled_cells = {
        CsvCellStyle{0, 1, Style{6, 0, AttrUnderline}},
    };
    require(app.add_card(std::move(csv)) == 4);

    Card folder = make_folder_card({105, 2}, 16, 5);
    FolderCardData& folder_data = std::get<FolderCardData>(folder.data);
    folder_data.name = "root";
    folder_data.entries = {
        FolderEntry{
            FolderEntryKind::Directory,
            0,
            "docs",
            kNoCard,
            true,
        },
        FolderEntry{
            FolderEntryKind::Card,
            1,
            "note",
            0,
            false,
        },
    };
    require(app.add_card(std::move(folder)) == 5);

    Card text_art = make_empty_text_art_card({130, 2}, 1, 1);
    std::get<TextCardData>(text_art.data).lines = {"X"};
    require(app.add_card(std::move(text_art)) == 6);

    Edge edge;
    edge.source = {0, PortSide::Right};
    edge.target = {1, PortSide::Left};
    edge.mode = RouteMode::Manual;
    edge.route_bounds = {13, 2, 20, 3};
    edge.points = {{13, 2}, {19, 2}};
    require(app.board.add_edge(std::move(edge)) == 0);
    require(app.glyphs.insert({5, 9}, U'中'));
    require(app.glyphs.insert({-1, 4}, U'A'));


    // Include tombstones and rebuild all format-owned state as the editor does.
    const CardId removed = app.add_card(make_plain_text_note({200, 0}, 12, 5));
    require(app.erase_cards(&removed, 1));
    app.board.edges.emplace_back(std::nullopt);
    for (auto& slot : app.board.cards) {
        if (!slot) continue;
        app.formats[slot->static_format].rebuild(slot->data);
        if (auto* text = std::get_if<TextCardData>(&slot->data)) {
            TextSession session;
            begin_text_syntax(session, *text);
        }
    }
    for (auto& slot : app.board.edges) {
        if (!slot) continue;
        slot->state = validate_edge_collision(app.board, app.spatial, slot->source,
                                              &slot->target, slot->points)
            ? RouteState::Ready : RouteState::Blocked;
    }
}
