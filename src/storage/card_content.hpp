#pragma once

#include "../model.hpp"

#include <istream>
#include <ostream>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

constexpr u64 kMaximumContentCardBytes =
    256ULL * 1024ULL * 1024ULL;
constexpr u64 kMaximumContentAllocationBytes =
    512ULL * 1024ULL * 1024ULL;
constexpr std::size_t kMaximumContentTextLines = 100'000;

template<class Lines>
static void write_text_lines(
    std::ostream& output,
    const Lines& lines
) {
    for (std::size_t i = 0; i < lines.size(); ++i) {
        output.write(lines[i].data(), lines[i].size());

        if (i + 1 < lines.size()) {
            output.put('\n');
        }
    }
}

template<class Lines>
static bool read_text_lines(
    std::istream& input,
    Lines& lines
) {
    lines.clear();
    std::string line;
    bool ended_with_newline = false;
    u64 byte_count = 0;
    char ch;

    while (input.get(ch)) {
        ++byte_count;

        if (byte_count > kMaximumContentCardBytes) {
            return false;
        }

        if (ch == '\n' || ch == '\r') {
            if (ch == '\r' && input.peek() == '\n') {
                input.get(ch);
                ++byte_count;

                if (byte_count > kMaximumContentCardBytes) {
                    return false;
                }
            }

            if (lines.size() >= kMaximumContentTextLines) {
                return false;
            }

            lines.push_back(std::move(line));
            line.clear();
            ended_with_newline = true;
        } else {
            line.push_back(ch);
            ended_with_newline = false;
        }
    }

    if (input.bad() || lines.size() >= kMaximumContentTextLines) {
        return false;
    }

    if (ended_with_newline) {
        lines.emplace_back();
    } else {
        lines.push_back(std::move(line));
    }

    return true;
}

static void write_todo_text(
    std::ostream& output,
    const TodoCardData& data
) {
    for (std::size_t i = 0; i < data.items.size(); ++i) {
        const TodoItem& item = data.items[i];
        output << (item.done ? "- [x] " : "- [ ] ");
        output.write(item.text.data(), item.text.size());

        if (i + 1 < data.items.size()) {
            output.put('\n');
        }
    }
}

[[maybe_unused]] static bool read_todo_text(
    std::istream& input,
    TodoCardData& data
) {
    std::vector<std::string> lines;

    if (!read_text_lines(input, lines)) {
        return false;
    }

    const TodoItems& metadata = data.items;
    TodoItems items;
    items.reserve(lines.size());

    for (std::size_t i = 0; i < lines.size(); ++i) {
        std::string& line = lines[i];
        bool done = false;
        std::size_t begin = 0;

        if (line.starts_with("- [x] ")) {
            done = true;
            begin = 6;
        } else if (line.starts_with("- [ ] ")) {
            begin = 6;
        }

        if (begin != 0) {
            line.erase(0, begin);
        }

        TodoItem item{std::move(line), done};

        if (i < metadata.size()) {
            item.style = metadata[i].style;
        }

        items.push_back(std::move(item));
    }

    data.items = std::move(items);
    return true;
}

static void write_csv_cell(
    std::ostream& output,
    std::string_view cell
) {
    const bool quote =
        cell.find_first_of(",\"\r\n") != std::string_view::npos;

    if (!quote) {
        output.write(cell.data(), cell.size());
        return;
    }

    output.put('"');

    for (char ch : cell) {
        if (ch == '"') {
            output.put('"');
        }

        output.put(ch);
    }

    output.put('"');
}

static void write_csv(
    std::ostream& output,
    const CsvCardData& data
) {
    for (std::size_t row = 0; row < data.cells.size(); ++row) {
        for (std::size_t column = 0;
             column < data.cells[row].size();
             ++column) {
            if (column != 0) {
                output.put(',');
            }

            // A single empty cell must be explicit: a trailing blank line
            // would otherwise be consumed as the previous record's newline.
            if (data.cells[row].size() == 1 && data.cells[row][column].empty()) {
                output << "\"\"";
            } else {
                write_csv_cell(output, data.cells[row][column]);
            }
        }

        if (row + 1 < data.cells.size()) {
            output.put('\n');
        }
    }
}

enum class CsvErrorCode {
    None,
    UnexpectedQuote,
    UnexpectedAfterQuote,
    UnterminatedQuote,
    ResourceLimit,
    InputError,
};

struct CsvParseError {
    CsvErrorCode code = CsvErrorCode::None;
    u64 line = 1;
    u64 column = 1;
};

static bool read_csv(
    std::istream& input,
    CsvCardData& data,
    CsvParseError* error = nullptr
) {
    constexpr u64 kMaximumCsvBytes = kMaximumContentCardBytes;
    constexpr std::size_t kMaximumCsvRows = 1'000'000;
    constexpr std::size_t kMaximumCsvCells = 10'000'000;

    enum class State {
        FieldStart,
        Unquoted,
        Quoted,
        QuoteClosed,
    };

    const auto fail = [&](CsvErrorCode code, u64 line, u64 column) {
        if (error != nullptr) {
            *error = {code, line, column};
        }
        return false;
    };

    std::vector<std::vector<std::string>> cells;
    std::vector<std::string> row;
    std::string cell;
    State state = State::FieldStart;
    bool saw_any = false;
    bool at_record_start = true;
    std::size_t cell_count = 0;
    u64 byte_count = 0;
    u64 line = 1;
    u64 column = 0;
    char ch;
    const auto allocation_fits = [&] {
        const u64 rows = static_cast<u64>(cells.size()) + 1;
        const u64 strings = static_cast<u64>(cell_count) + 1;
        const u64 overhead =
            rows * sizeof(std::vector<std::string>) +
            strings * sizeof(std::string);
        return
            byte_count <= kMaximumContentAllocationBytes / 2 &&
            overhead <=
                kMaximumContentAllocationBytes - 2 * byte_count;
    };

    while (input.get(ch)) {
        saw_any = true;
        ++byte_count;
        ++column;

        if (byte_count > kMaximumCsvBytes) {
            return fail(CsvErrorCode::ResourceLimit, line, column);
        }

        if (state == State::Quoted) {
            if (ch == '"') {
                if (input.peek() == '"') {
                    input.get(ch);
                    ++byte_count;
                    ++column;

                    if (byte_count > kMaximumCsvBytes) {
                        return fail(
                            CsvErrorCode::ResourceLimit,
                            line,
                            column
                        );
                    }

                    cell.push_back('"');
                } else {
                    state = State::QuoteClosed;
                }
            } else {
                cell.push_back(ch);

                if (ch == '\n') {
                    ++line;
                    column = 0;
                }
            }
            continue;
        }

        if (state == State::QuoteClosed) {
            if (ch != ',' && ch != '\n' && ch != '\r') {
                return fail(
                    CsvErrorCode::UnexpectedAfterQuote,
                    line,
                    column
                );
            }
        } else if (ch == '"') {
            if (state != State::FieldStart) {
                return fail(
                    CsvErrorCode::UnexpectedQuote,
                    line,
                    column
                );
            }

            state = State::Quoted;
            at_record_start = false;
            continue;
        } else if (ch != ',' && ch != '\n' && ch != '\r') {
            cell.push_back(ch);
            state = State::Unquoted;
            at_record_start = false;
            continue;
        }

        if (ch == ',') {
            row.push_back(std::move(cell));
            cell.clear();
            ++cell_count;

            if (cell_count > kMaximumCsvCells) {
                return fail(CsvErrorCode::ResourceLimit, line, column);
            }

            if (!allocation_fits()) {
                return fail(CsvErrorCode::ResourceLimit, line, column);
            }

            state = State::FieldStart;
            at_record_start = false;
        } else {
            if (ch == '\r' && input.peek() == '\n') {
                input.get(ch);
                ++byte_count;

                if (byte_count > kMaximumCsvBytes) {
                    return fail(
                        CsvErrorCode::ResourceLimit,
                        line,
                        column
                    );
                }
            }

            row.push_back(std::move(cell));
            cell.clear();
            ++cell_count;
            cells.push_back(std::move(row));
            row.clear();
            state = State::FieldStart;
            at_record_start = true;
            ++line;
            column = 0;

            if (
                cell_count > kMaximumCsvCells ||
                cells.size() > kMaximumCsvRows
            ) {
                return fail(CsvErrorCode::ResourceLimit, line, column);
            }

            if (!allocation_fits()) {
                return fail(CsvErrorCode::ResourceLimit, line, column);
            }
        }
    }

    if (input.bad()) {
        return fail(CsvErrorCode::InputError, line, column);
    }

    if (state == State::Quoted) {
        return fail(CsvErrorCode::UnterminatedQuote, line, column);
    }

    if (!at_record_start) {
        row.push_back(std::move(cell));
        ++cell_count;
        cells.push_back(std::move(row));

        if (
            cell_count > kMaximumCsvCells ||
            cells.size() > kMaximumCsvRows
        ) {
            return fail(CsvErrorCode::ResourceLimit, line, column);
        }

        if (!allocation_fits()) {
            return fail(CsvErrorCode::ResourceLimit, line, column);
        }
    }

    if (!saw_any) {
        cells.emplace_back(1);
    }

    data.cells = std::move(cells);

    if (error != nullptr) {
        *error = {};
    }

    return true;
}

[[maybe_unused]] static bool write_card_content(
    std::ostream& output,
    SaveFormat format,
    const CardData& data
) {
    switch (format) {
        case SaveFormat::PlainText:
        case SaveFormat::Markdown:
            write_text_lines(
                output,
                std::get<TextCardData>(data).lines
            );
            break;

        case SaveFormat::TodoText:
            write_todo_text(
                output,
                std::get<TodoCardData>(data)
            );
            break;

        case SaveFormat::Csv:
            write_csv(output, std::get<CsvCardData>(data));
            break;

        case SaveFormat::FolderTree:
            return false;
    }

    return static_cast<bool>(output);
}
