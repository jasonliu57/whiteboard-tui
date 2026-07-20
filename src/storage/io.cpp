#include "api.hpp"

#include "project.hpp"
#include "card_content.hpp"
#include "../formats/registry.hpp"
#include "string_view_stream.hpp"

#include <new>

namespace whiteboard::io {

namespace {

void describe_exception(std::string* error, const char* message) noexcept {
    if (error != nullptr) {
        try {
            *error = message;
        } catch (...) {
            // Error reporting must not propagate another allocation failure.
        }
    }
}

bool save_format_data_matches(
    SaveFormat format,
    const CardData& data
) noexcept {
    switch (format) {
        case SaveFormat::PlainText:
        case SaveFormat::Markdown:
            return std::holds_alternative<TextCardData>(data);
        case SaveFormat::TodoText:
            return std::holds_alternative<TodoCardData>(data);
        case SaveFormat::Csv:
            return std::holds_alternative<CsvCardData>(data);
        case SaveFormat::FolderTree:
            return std::holds_alternative<FolderCardData>(data);
    }

    return false;
}

} // namespace

bool encode_project(std::ostream& output, const Board& board,
                    const GlyphLayer& glyphs, std::string* error) {
    if (error) error->clear();
    try {
        if (::write_main_file_content(output, board, glyphs)) return true;
        describe_exception(error, "project serialization failed");
    } catch (const std::bad_alloc&) {
        describe_exception(error, "not enough memory for project encoding");
    } catch (...) {
        describe_exception(error, "project serialization failed");
    }
    return false;
}

bool decode_project(std::istream& input, u64 size, Board& board,
                    CardSpatial& spatial, GlyphLayer& glyphs,
                    const CardFormats& formats, std::string* error, u64 allocation_budget) {
    if (error) *error = "invalid or damaged project";
    try {
        return ::read_main_file_content(input, size, board, spatial, glyphs,
                                        formats, error, allocation_budget);
    } catch (const std::bad_alloc&) {
        describe_exception(error, "not enough memory for project decoding");
    } catch (...) {
        describe_exception(error, "project decoding failed");
    }
    return false;
}

bool read_card_content(
    std::string_view content,
    SaveFormat format,
    CardData& data
) {
    try {
        if (
            format == SaveFormat::FolderTree ||
            !save_format_data_matches(format, data)
        ) {
            return false;
        }

        StringViewInputStream input{content};

        switch (format) {
            case SaveFormat::PlainText:
            case SaveFormat::Markdown: {
                TextLines lines;

                if (!::read_text_lines(input, lines)) {
                    return false;
                }

                std::get<TextCardData>(data).lines = std::move(lines);
                break;
            }
            case SaveFormat::TodoText:
                return ::read_todo_text(
                    input,
                    std::get<TodoCardData>(data)
                );
            case SaveFormat::Csv:
                return ::read_csv(input, std::get<CsvCardData>(data));
            case SaveFormat::FolderTree:
                return false;
        }

        return !input.bad();
    } catch (const std::bad_alloc&) {
        return false;
    } catch (...) {
        return false;
    }
}

bool write_card_content(
    std::ostream& output,
    SaveFormat format,
    const CardData& data
) {
    return
        save_format_data_matches(format, data) &&
        ::write_card_content(output, format, data);
}

bool write_exchange_card_content(
    std::ostream& output,
    const Card& card
) {
    if (card_save_format(card) != SaveFormat::FolderTree) {
        return whiteboard::io::write_card_content(
            output,
            card_save_format(card),
            card.data
        );
    }

    const FolderCardData& folder = std::get<FolderCardData>(card.data);
    output << "ROOT\t" << folder.name << '\n';

    for (const FolderEntry& entry : folder.entries) {
        output << entry.depth << '\t'
               << (entry.kind == FolderEntryKind::Directory ? "DIR" : "CARD")
               << '\t';

        if (entry.kind == FolderEntryKind::Card) {
            output << entry.target;
        } else {
            output << '-';
        }

        output << '\t' << (entry.collapsed ? 1 : 0)
               << '\t' << entry.name << '\n';
    }

    return static_cast<bool>(output);
}

} // namespace whiteboard::io
