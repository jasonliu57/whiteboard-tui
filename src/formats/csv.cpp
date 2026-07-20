#include "registry.hpp"
#include "draw.hpp"
constexpr i32 kCsvMinimumColumnWidth = 3;
constexpr i32 kCsvMaximumColumnWidth = 30;

static bool csv_style_before(
    const CsvCellStyle& style,
    u32 row,
    u32 column
) {
    return
        style.row < row ||
        (style.row == row && style.column < column);
}

static CsvCellStyles::iterator csv_style_at(
    CsvCellStyles& styles,
    u32 row,
    u32 column
) {
    return std::lower_bound(
        styles.begin(),
        styles.end(),
        std::pair{row, column},
        [](const CsvCellStyle& style, const std::pair<u32, u32>& cell) {
            return csv_style_before(style, cell.first, cell.second);
        }
    );
}

static CsvCellStyles::const_iterator csv_style_at(
    const CsvCellStyles& styles,
    u32 row,
    u32 column
) {
    return std::lower_bound(
        styles.begin(),
        styles.end(),
        std::pair{row, column},
        [](const CsvCellStyle& style, const std::pair<u32, u32>& cell) {
            return csv_style_before(style, cell.first, cell.second);
        }
    );
}

static void canonicalize_csv_styles(CsvCardData& data) {
    CsvCellStyles previous =
        std::move(data.styled_cells);
    data.styled_cells.clear();
    data.styled_cells.reserve(previous.size());

    for (CsvCellStyle style : previous) {
        if (
            style.row >= data.cells.size() ||
            style.column >= data.cells[style.row].size()
        ) {
            continue;
        }

        style.style = canonical_style(style.style);

        if (data.styled_cells.empty()) {
            data.styled_cells.push_back(style);
            continue;
        }

        CsvCellStyle& last = data.styled_cells.back();

        if (csv_style_before(last, style.row, style.column)) {
            data.styled_cells.push_back(style);
            continue;
        }

        if (last.row == style.row && last.column == style.column) {
            last = style;
            continue;
        }

        auto position = csv_style_at(
            data.styled_cells,
            style.row,
            style.column
        );

        if (
            position != data.styled_cells.end() &&
            position->row == style.row &&
            position->column == style.column
        ) {
            *position = style;
        } else {
            data.styled_cells.insert(position, style);
        }
    }
}

static void rebuild_csv(CardData& card_data) {
    CsvCardData& data = std::get<CsvCardData>(card_data);

    if (data.cells.empty()) {
        data.cells.emplace_back(1);
    }

    std::size_t columns = 1;

    for (const auto& row : data.cells) {
        columns = std::max(columns, row.size());
    }

    for (auto& row : data.cells) {
        row.resize(columns);
    }

    data.column_widths.resize(columns, 10);

    for (i32& width : data.column_widths) {
        width = std::clamp(
            width,
            kCsvMinimumColumnWidth,
            kCsvMaximumColumnWidth
        );
    }

    canonicalize_csv_styles(data);
}

static Extent measure_csv(const CardData& data) {
    return std::get<CsvCardData>(data).layout;
}

static void begin_csv(
    FormatSession& session,
    const CardData&
) {
    session = CsvSession{};
}

static void keep_csv_row_visible(
    const CsvCardData& data,
    CsvSession& session
) {
    if (session.row >= data.cells.size()) {
        session.row = static_cast<u32>(data.cells.size() - 1);
    }

    const u32 visible_rows =
        static_cast<u32>(data.layout.height - 2);

    if (session.row < session.row_scroll) {
        session.row_scroll = session.row;
    } else if (session.row >= session.row_scroll + visible_rows) {
        session.row_scroll = session.row - visible_rows + 1;
    }
}

static void keep_csv_column_visible(
    const CsvCardData& data,
    CsvSession& session
) {
    if (session.column >= data.cells[0].size()) {
        session.column = static_cast<u32>(data.cells[0].size() - 1);
    }

    if (session.column < session.column_scroll) {
        session.column_scroll = session.column;
    }

    i32 cells = 0;

    for (u32 column = session.column_scroll;
         column <= session.column;
         ++column) {
        cells += data.column_widths[column];
    }

    while (
        cells > data.layout.width - 2 &&
        session.column_scroll < session.column
    ) {
        cells -= data.column_widths[session.column_scroll];
        ++session.column_scroll;
    }
}

static void keep_csv_visible(
    const CsvCardData& data,
    CsvSession& session
) {
    keep_csv_row_visible(data, session);
    keep_csv_column_visible(data, session);
}

static void draw_csv(
    Screen& screen,
    const CardData& card_data,
    CardId id,
    i32 x,
    i32 y,
    const CardFormat& format,
    CardVisualState visual_state,
    const FormatSession* active_session
) {
    const CsvCardData& data = std::get<CsvCardData>(card_data);
    const CsvSession* session =
        active_session == nullptr
            ? nullptr
            : &std::get<CsvSession>(*active_session);

    draw_box(
        screen,
        data.layout,
        id,
        x,
        y,
        format,
        visual_state
    );

    const i32 right = x + data.layout.width - 1;
    const i32 inner_height = data.layout.height - 2;
    const u32 row_scroll = session == nullptr ? 0 : session->row_scroll;
    const u32 column_scroll =
        session == nullptr ? 0 : session->column_scroll;
    const VisibleRowRange rows = visible_rows(
        screen,
        y + 1,
        inner_height
    );
    std::size_t style_index = static_cast<std::size_t>(
        csv_style_at(
            data.styled_cells,
            row_scroll + static_cast<u32>(rows.first),
            column_scroll
        ) - data.styled_cells.begin()
    );

    for (i32 local_row = rows.first;
         local_row < rows.last;
         ++local_row) {
        const u32 row = row_scroll + static_cast<u32>(local_row);

        if (row >= data.cells.size()) {
            break;
        }

        i32 cell_x = x + 1;

        for (u32 column = column_scroll;
             column < data.cells[row].size() &&
             cell_x < right &&
             cell_x < screen.width();
             ++column) {
            const i32 width = std::min(
                data.column_widths[column],
                right - cell_x
            );
            while (
                style_index < data.styled_cells.size() &&
                csv_style_before(
                    data.styled_cells[style_index],
                    row,
                    column
                )
            ) {
                ++style_index;
            }

            const Style style =
                style_index < data.styled_cells.size() &&
                data.styled_cells[style_index].row == row &&
                data.styled_cells[style_index].column == column
                    ? data.styled_cells[style_index].style
                    : format.body;

            if (cell_x + width > 0) {
                draw_string(
                    screen,
                    cell_x,
                    y + 1 + local_row,
                    width,
                    data.cells[row][column],
                    style,
                    id
                );
            }

            if (
                session != nullptr &&
                row == session->row &&
                column == session->column
            ) {
                screen.invert_span(
                    cell_x,
                    y + 1 + local_row,
                    width,
                    id
                );
            }

            cell_x += width;

            if (cell_x < right) {
                screen.paint(
                    cell_x,
                    y + 1 + local_row,
                    {U'│', 1},
                    format.border,
                    id
                );
                ++cell_x;
            }
        }
    }
}

static FormatAction resize_csv(
    FormatContext& context,
    const InputEvent& event
) {
    CsvCardData& data = std::get<CsvCardData>(context.data);
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

    CsvLayoutUndo undo{};
    undo.layout = data.layout;
    data.layout = next;
    keep_csv_visible(data, std::get<CsvSession>(context.session));
    return stored_layout_action(FormatUndo{std::move(undo)});
}

static FormatAction input_csv(
    FormatContext& context,
    const InputEvent& event
) {
    FormatAction action = resize_csv(context, event);

    if (action.handled) {
        return action;
    }

    CsvCardData& data = std::get<CsvCardData>(context.data);
    CsvSession& session = std::get<CsvSession>(context.session);

    switch (event.key) {
        case Key::Left:
            if (session.column > 0) {
                --session.column;
            }
            keep_csv_visible(data, session);
            return view_action();

        case Key::Right:
            if (session.column + 1 < data.cells[0].size()) {
                ++session.column;
            }
            keep_csv_visible(data, session);
            return view_action();

        case Key::Up:
            if (session.row > 0) {
                --session.row;
            }
            keep_csv_row_visible(data, session);
            return view_action();

        case Key::Down:
            if (session.row + 1 < data.cells.size()) {
                ++session.row;
            }
            keep_csv_row_visible(data, session);
            return view_action();

        case Key::Tab:
            if (event.shift) {
                if (session.column > 0) {
                    --session.column;
                } else if (session.row > 0) {
                    --session.row;
                    session.column = static_cast<u32>(
                        data.cells[session.row].size() - 1
                    );
                }
            } else if (session.column + 1 < data.cells[0].size()) {
                ++session.column;
            } else if (session.row + 1 < data.cells.size()) {
                ++session.row;
                session.column = 0;
            }
            keep_csv_visible(data, session);
            return view_action();

        case Key::Home:
            session.column = 0;
            keep_csv_visible(data, session);
            return view_action();

        case Key::End:
            session.column = static_cast<u32>(
                data.cells[session.row].size() - 1
            );
            keep_csv_visible(data, session);
            return view_action();

        case Key::PageUp: {
            CsvColumnWidths widths(
                data.cells[0].size(),
                kCsvMinimumColumnWidth
            );

            for (const auto& row : data.cells) {
                for (u32 column = 0; column < row.size(); ++column) {
                    widths[column] = std::max(
                        widths[column],
                        std::min(
                            kCsvMaximumColumnWidth,
                            cell_column(
                                row[column],
                                static_cast<u32>(row[column].size())
                            ) + 1
                        )
                    );
                }
            }

            if (widths == data.column_widths) {
                return view_action();
            }

            CsvWidthsUndo undo{};
            undo.widths = std::move(data.column_widths);
            data.column_widths = std::move(widths);
            keep_csv_visible(data, session);
            return stored_action(FormatUndo{std::move(undo)});
        }

        case Key::Enter:
            if (session.row + 1 < data.cells.size()) {
                ++session.row;
                keep_csv_row_visible(data, session);
                return view_action();
            } else {
                const u32 previous = session.row;
                const u32 inserted = static_cast<u32>(data.cells.size());
                CsvRowUndo undo{};
                undo.row = inserted;
                undo.row_present = false;
                undo.current_row = inserted;
                undo.replacement_row = previous;
                undo.current_column = session.column;
                undo.replacement_column = session.column;
                data.cells.emplace_back(data.cells[0].size());
                session.row = inserted;
                keep_csv_row_visible(data, session);
                return stored_action(FormatUndo{std::move(undo)});
            }

        case Key::Delete: {
            std::string& cell = data.cells[session.row][session.column];

            if (cell.empty()) {
                return view_action();
            }

            CsvTextUndo undo{};
            undo.row = session.row;
            undo.column = session.column;
            undo.text = std::move(cell);
            cell.clear();
            return stored_action(FormatUndo{std::move(undo)});
        }

        case Key::Backspace: {
            std::string& cell = data.cells[session.row][session.column];

            if (cell.empty()) {
                return view_action();
            }

            const u32 begin = previous_utf8_byte(
                cell,
                static_cast<u32>(cell.size())
            );
            CsvTextUndo undo{};
            undo.row = session.row;
            undo.column = session.column;
            undo.begin_byte = begin;
            undo.end_byte = begin;
            undo.text = cell.substr(begin);
            cell.erase(begin);
            return stored_action(FormatUndo{std::move(undo)});
        }

        case Key::CtrlX: {
            const u32 erased = session.row;

            if (data.cells.size() == 1) {
                CsvReplaceRowUndo undo{};
                undo.row = 0;
                undo.cells = std::move(data.cells[0]);
                undo.styles = std::move(data.styled_cells);
                data.cells[0].resize(undo.cells.size());
                data.styled_cells.clear();
                return stored_action(FormatUndo{std::move(undo)});
            } else {
                const u32 next = std::min<u32>(
                    erased,
                    static_cast<u32>(data.cells.size() - 2)
                );
                CsvRowUndo undo{};
                undo.row = erased;
                undo.row_present = true;
                undo.cells = std::move(data.cells[erased]);
                undo.current_row = next;
                undo.replacement_row = erased;
                undo.current_column = session.column;
                undo.replacement_column = session.column;

                data.cells.erase(data.cells.begin() + erased);
                std::size_t output = 0;

                for (CsvCellStyle style : data.styled_cells) {
                    if (style.row == erased) {
                        undo.styles.push_back(style);
                        continue;
                    }

                    if (style.row > erased) {
                        --style.row;
                    }
                    data.styled_cells[output++] = style;
                }

                data.styled_cells.resize(output);

                session.row = next;
                keep_csv_row_visible(data, session);
                return stored_action(FormatUndo{std::move(undo)});
            }
        }

        case Key::CtrlB: {
            auto position = csv_style_at(
                data.styled_cells,
                session.row,
                session.column
            );
            CsvStyleUndo undo{};
            undo.row = session.row;
            undo.column = session.column;

            if (
                position == data.styled_cells.end() ||
                position->row != session.row ||
                position->column != session.column
            ) {
                undo.style_present = false;
                data.styled_cells.insert(position, {
                    session.row,
                    session.column,
                    Style{3, 0, AttrBold}
                });
            } else {
                undo.style_present = true;
                undo.style = position->style;
                position->style.foreground = static_cast<u8>(
                    position->style.foreground == 6
                        ? 1
                        : position->style.foreground + 1
                );
            }

            return stored_action(FormatUndo{std::move(undo)});
        }

        case Key::CtrlC:
            context.clipboard =
                data.cells[session.row][session.column];
            return view_action();

        case Key::CtrlV: {
            const std::string* text =
                std::get_if<std::string>(&context.clipboard);

            if (text == nullptr) {
                return view_action();
            }

            std::string& cell = data.cells[session.row][session.column];
            const u32 begin = static_cast<u32>(cell.size());

            if (text->empty()) {
                return view_action();
            }

            cell.append(*text);
            CsvTextUndo undo{};
            undo.row = session.row;
            undo.column = session.column;
            undo.begin_byte = begin;
            undo.end_byte = static_cast<u32>(cell.size());
            return stored_action(FormatUndo{std::move(undo)});
        }

        case Key::Text:
        case Key::Paste: {
            if (event.text.empty()) {
                return view_action();
            }

            std::string& cell = data.cells[session.row][session.column];
            const u32 begin = static_cast<u32>(cell.size());
            cell.append(event.text);
            CsvTextUndo undo{};
            undo.row = session.row;
            undo.column = session.column;
            undo.begin_byte = begin;
            undo.end_byte = static_cast<u32>(cell.size());
            return stored_action(FormatUndo{std::move(undo)});
        }

        default:
            return {};
    }
}

static void swap_csv_undo(
    CardData& card_data,
    FormatSession* format_session,
    FormatUndo& undo
) {
    CsvCardData& data = std::get<CsvCardData>(card_data);
    CsvSession* session = format_session == nullptr
        ? nullptr
        : &std::get<CsvSession>(*format_session);
    bool keep_all_visible = false;
    bool keep_row_visible = false;

    if (auto* change = std::get_if<CsvLayoutUndo>(&undo)) {
        std::swap(data.layout, change->layout);
        keep_all_visible = true;
    } else if (auto* change = std::get_if<CsvTextUndo>(&undo)) {
        std::string& text = data.cells[change->row][change->column];
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
    } else if (auto* change = std::get_if<CsvStyleUndo>(&undo)) {
        auto position = csv_style_at(
            data.styled_cells,
            change->row,
            change->column
        );
        const bool current_present =
            position != data.styled_cells.end() &&
            position->row == change->row &&
            position->column == change->column;
        const Style current = current_present
            ? position->style
            : Style{};

        if (change->style_present) {
            if (current_present) {
                position->style = change->style;
            } else {
                data.styled_cells.insert(position, {
                    change->row,
                    change->column,
                    change->style,
                });
            }
        } else if (current_present) {
            data.styled_cells.erase(position);
        }

        change->style_present = current_present;
        change->style = current;
    } else if (auto* change = std::get_if<CsvRowUndo>(&undo)) {
        if (change->row_present) {
            for (CsvCellStyle& style : data.styled_cells) {
                if (style.row >= change->row) {
                    ++style.row;
                }
            }

            data.cells.insert(
                data.cells.begin() + change->row,
                std::move(change->cells)
            );

            for (const CsvCellStyle& style : change->styles) {
                data.styled_cells.insert(
                    csv_style_at(
                        data.styled_cells,
                        style.row,
                        style.column
                    ),
                    style
                );
            }
            change->styles.clear();
            change->row_present = false;
        } else {
            change->cells = std::move(data.cells[change->row]);
            data.cells.erase(data.cells.begin() + change->row);
            change->styles.clear();
            std::size_t output = 0;

            for (CsvCellStyle style : data.styled_cells) {
                if (style.row == change->row) {
                    change->styles.push_back(style);
                    continue;
                }

                if (style.row > change->row) {
                    --style.row;
                }
                data.styled_cells[output++] = style;
            }
            data.styled_cells.resize(output);
            change->row_present = true;
        }

        if (session != nullptr) {
            session->row = change->replacement_row;
            session->column = change->replacement_column;
        }

        std::swap(change->current_row, change->replacement_row);
        std::swap(change->current_column, change->replacement_column);
        keep_row_visible = true;
    } else if (auto* change = std::get_if<CsvReplaceRowUndo>(&undo)) {
        std::swap(data.cells[change->row], change->cells);
        CsvCellStyles current;
        std::size_t output = 0;

        for (CsvCellStyle style : data.styled_cells) {
            if (style.row == change->row) {
                current.push_back(style);
            } else {
                data.styled_cells[output++] = style;
            }
        }
        data.styled_cells.resize(output);

        for (const CsvCellStyle& style : change->styles) {
            data.styled_cells.insert(
                csv_style_at(
                    data.styled_cells,
                    style.row,
                    style.column
                ),
                style
            );
        }
        change->styles = std::move(current);
    } else if (auto* change = std::get_if<CsvWidthsUndo>(&undo)) {
        std::swap(data.column_widths, change->widths);
        keep_all_visible = true;
    }

    if (session != nullptr) {
        if (keep_all_visible) {
            keep_csv_visible(data, *session);
        } else if (keep_row_visible) {
            keep_csv_row_visible(data, *session);
        }
    }
}

CardFormat make_csv_format() {
    CardFormat format;
    format.name = "csv";
    format.data_kind = CardDataKind::Csv;
    apply_generated_card_format_contract(format, kCardFormatCsv);
    format.border = Style{6, 0, AttrBold};
    format.body = Style{7, 0, AttrNone};
    format.title = Style{6, 0, AttrBold};
    format.active_border = Style{3, 0, AttrBold};
    format.measure = measure_csv;
    format.draw = draw_csv;
    format.begin = begin_csv;
    format.input = input_csv;
    format.rebuild = rebuild_csv;
    format.swap_undo = swap_csv_undo;
    format.create_empty = make_csv_card;
    return format;
}

Card make_csv_card(
    Pos pos,
    i32 width,
    i32 height
) {
    Card card;
    card.pos = pos;
    card.static_format = kCsvStaticFormatId;
    CsvCardData& data = card.data.emplace<CsvCardData>();
    data.layout = {width, height};
    return card;
}
