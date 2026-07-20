#include "registry.hpp"
#include "validation.hpp"

#include <algorithm>
#include <array>
#include <charconv>

namespace {

bool registry_line_space(char ch) {
    return ch == ' ' || ch == '\t' || ch == '\r';
}

bool next_registry_word(
    std::string_view line,
    std::size_t& offset,
    std::string_view& word
) {
    while (offset < line.size() && registry_line_space(line[offset])) {
        ++offset;
    }

    if (offset == line.size()) {
        return false;
    }

    const std::size_t begin = offset;

    while (offset < line.size() && !registry_line_space(line[offset])) {
        ++offset;
    }

    word = line.substr(begin, offset - begin);
    return true;
}

template<class Integer>
bool parse_registry_integer(std::string_view text, Integer& value) {
    const auto [end, error] = std::from_chars(
        text.data(),
        text.data() + text.size(),
        value
    );
    return error == std::errc{} && end == text.data() + text.size();
}

} // namespace

bool create_registered_card(
    const CardFormats& formats,
    StaticFormatId id,
    Pos position,
    Extent extent,
    Card& result
) {
    if (id >= formats.size()) {
        return false;
    }

    const CardFormat& format = formats[id];
    Rect bounds;

    if (
        format.create_empty == nullptr ||
        !extent_in_format(extent, format) ||
        !checked_rect_at(position, extent, bounds)
    ) {
        return false;
    }

    Card card = format.create_empty(
        position,
        extent.width,
        extent.height
    );

    if (
        card.pos != position ||
        card.static_format != id ||
        !card_data_matches(format.data_kind, card.data) ||
        format.measure == nullptr ||
        format.measure(card.data) != extent
    ) {
        return false;
    }

    result = std::move(card);
    return true;
}

RegisteredCardBatchResult build_registered_card_batch(
    const CardFormats& formats,
    std::string_view text,
    std::vector<Card>& result,
    u32& invalid_line
) {
    std::vector<Card> cards;
    cards.reserve(1 + static_cast<std::size_t>(std::count(
        text.begin(),
        text.end(),
        '\n'
    )));
    invalid_line = 0;

    for (std::size_t begin = 0; begin < text.size();) {
        std::size_t end = text.find('\n', begin);

        if (end == std::string_view::npos) {
            end = text.size();
        }

        ++invalid_line;
        const std::string_view line = text.substr(begin, end - begin);
        std::size_t offset = 0;
        std::string_view first;

        if (next_registry_word(line, offset, first)) {
            Card card;

            if (!create_registered_card(formats, line, card)) {
                return RegisteredCardBatchResult::InvalidLine;
            }

            cards.push_back(std::move(card));
        }

        begin = end + 1;
    }

    if (cards.empty()) {
        invalid_line = 0;
        return RegisteredCardBatchResult::Empty;
    }

    invalid_line = 0;
    result = std::move(cards);
    return RegisteredCardBatchResult::Success;
}

bool create_registered_card(
    const CardFormats& formats,
    std::string_view line,
    Card& result
) {
    std::array<std::string_view, 5> words;
    std::size_t offset = 0;

    for (std::string_view& word : words) {
        if (!next_registry_word(line, offset, word)) {
            return false;
        }
    }

    std::string_view extra;

    if (next_registry_word(line, offset, extra)) {
        return false;
    }

    StaticFormatId id = static_cast<StaticFormatId>(formats.size());

    for (StaticFormatId candidate = 0;
         candidate < formats.size();
         ++candidate) {
        if (words[0] == formats[candidate].name) {
            id = candidate;
            break;
        }
    }

    Pos position;
    Extent extent;

    return
        id < formats.size() &&
        parse_registry_integer(words[1], position.x) &&
        parse_registry_integer(words[2], position.y) &&
        parse_registry_integer(words[3], extent.width) &&
        parse_registry_integer(words[4], extent.height) &&
        create_registered_card(
            formats,
            id,
            position,
            extent,
            result
        );
}

CardFormats make_card_formats() {
    return {
        make_plain_text_note_format(),
        make_markdown_format(),
        make_code_format(),
        make_todo_format(),
        make_csv_format(),
        make_folder_format(),
        make_text_art_format(),
    };
}
