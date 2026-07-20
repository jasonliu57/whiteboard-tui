#include "internal.hpp"
#include "registry.hpp"
#include "text_edit.hpp"
#include "../render/screen.hpp"

Card make_empty_text_art_card(
    Pos pos,
    i32 width,
    i32 height
) {
    TextCardData data;
    data.layout = {width + 2, height + 2};
    data.language = kPlainTextLanguageId;

    Card card;
    card.pos = pos;
    card.static_format = kTextArtStaticFormatId;
    card.data = std::move(data);
    return card;
}

Rect text_art_frame(
    const GlyphLayer& glyphs,
    Rect selection
) {
    Rect frame = selection;

    for (i64 y = selection.top; y < selection.bottom; ++y) {
        const auto left = glyphs.anchor_at({selection.left, y});

        if (left != glyphs.cells.end()) {
            frame.left = std::min(frame.left, left->first.x);
        }

        const auto right = glyphs.anchor_at({
            selection.right - 1,
            y,
        });

        if (right != glyphs.cells.end()) {
            frame.right = std::max(
                frame.right,
                right->first.x + glyph_width(right->second)
            );
        }
    }

    return frame;
}

TextArtBuildResult make_text_art_card(
    const GlyphLayer& glyphs,
    Rect selection,
    std::vector<GlyphCell>& selected,
    Card& result
) {
    selected.clear();
    const u64 selection_width =
        static_cast<u64>(selection.right) -
        static_cast<u64>(selection.left);
    const u64 height =
        static_cast<u64>(selection.bottom) -
        static_cast<u64>(selection.top);

    if (
        selection_width >
            static_cast<u64>(kTextArtMaximumLayout.width) ||
        height >
            static_cast<u64>(kTextArtMaximumLayout.height)
    ) {
        return TextArtBuildResult::TooLarge;
    }

    const Rect frame = text_art_frame(glyphs, selection);
    const u64 width =
        static_cast<u64>(frame.right) -
        static_cast<u64>(frame.left);

    if (
        width >
            static_cast<u64>(kTextArtMaximumLayout.width)
    ) {
        return TextArtBuildResult::TooLarge;
    }

    TextLines lines;
    lines.reserve(static_cast<std::size_t>(height));

    for (u64 row = 0; row < height; ++row) {
        const i64 y = frame.top + static_cast<i64>(row);
        std::string line;
        line.reserve(static_cast<std::size_t>(width));

        for (i64 x = frame.left; x < frame.right;) {
            const auto cell = glyphs.cells.find({x, y});

            if (cell == glyphs.cells.end()) {
                line.push_back(' ');
                ++x;
                continue;
            }

            append_utf8(line, cell->second);
            selected.push_back({
                .pos = cell->first,
                .glyph = cell->second,
            });
            x += glyph_width(cell->second);
        }

        while (!line.empty() && line.back() == ' ') {
            line.pop_back();
        }

        lines.push_back(std::move(line));
    }

    if (selected.empty()) {
        return TextArtBuildResult::Empty;
    }

    TextCardData data;
    data.layout = {
        static_cast<i32>(width) + 2,
        static_cast<i32>(height) + 2,
    };
    data.language = kPlainTextLanguageId;
    data.lines = std::move(lines);

    Card card;
    card.pos = {frame.left, frame.top};
    card.static_format = kTextArtStaticFormatId;
    card.data = std::move(data);
    result = std::move(card);
    return TextArtBuildResult::Success;
}

static Extent measure_text_art_card(const CardData& card_data) {
    const Extent layout =
        std::get<TextCardData>(card_data).layout;
    return {
        layout.width - 2,
        layout.height - 2,
    };
}

static void draw_text_art_card(
    Screen& screen,
    const CardData& card_data,
    CardId id,
    i32 x,
    i32 y,
    const CardFormat& format,
    CardVisualState visual_state,
    const FormatSession* active_session
) {
    draw_text_card(
        screen,
        card_data,
        id,
        x,
        y,
        format,
        visual_state,
        active_session
    );

    if (visual_state != CardVisualState::Selected) {
        return;
    }

    const Extent extent = measure_text_art_card(card_data);

    for (i32 row = 0; row < extent.height; ++row) {
        screen.invert_span(x, y + row, extent.width, id);
    }
}

TextArtGlyphResult make_text_art_glyphs(
    const Card& card,
    std::vector<GlyphCell>& result
) {
    const TextCardData& data = std::get<TextCardData>(card.data);
    const i32 width = data.layout.width - 2;
    const i32 height = data.layout.height - 2;
    const u32 rows = static_cast<u32>(std::min<std::size_t>(
        data.lines.size(),
        static_cast<std::size_t>(height)
    ));
    result.clear();

    for (u32 row = 0; row < rows; ++row) {
        const std::string& line = data.lines[row];
        i32 cell = 0;

        for (u32 byte = 0; byte < line.size();) {
            if (cell >= width) {
                break;
            }

            const Rune rune = decode_utf8(line, byte);
            const i32 rune_width = text_visual_rune_width(
                rune.codepoint,
                cell
            );

            if (
                rune.codepoint != U' ' &&
                rune.codepoint != U'\t'
            ) {
                if (!stored_glyph(rune.codepoint)) {
                    result.clear();
                    return TextArtGlyphResult::UnsupportedGlyph;
                }

                if (cell + rune_width <= width) {
                    Pos position;

                    if (
                        !translate_glyph_position(
                            card.pos,
                            {cell, static_cast<i64>(row)},
                            position
                        ) ||
                        !valid_glyph_position(position, rune_width)
                    ) {
                        result.clear();
                        return TextArtGlyphResult::OutsideCoordinateRange;
                    }

                    result.push_back({
                        .pos = position,
                        .glyph = rune.codepoint,
                    });
                }
            }

            cell += rune_width;
            byte += rune.bytes;
        }
    }

    return TextArtGlyphResult::Success;
}

static FormatAction input_text_art(
    FormatContext& context,
    const InputEvent& event
) {
    if (
        event.ctrl &&
        (
            event.key == Key::Left ||
            event.key == Key::Right ||
            event.key == Key::Up ||
            event.key == Key::Down
        )
    ) {
        return view_action();
    }

    if (event.key == Key::CtrlB) {
        return bold_plain_text_selection(context);
    }

    return handle_text_input(context, event, false);
}

CardFormat make_text_art_format() {
    CardFormat format = make_plain_text_note_format();
    format.name = "text-art";
    apply_generated_card_format_contract(format, kCardFormatTextArt);
    format.first_line_is_title = false;
    format.borderless = true;
    format.measure = measure_text_art_card;
    format.draw = draw_text_art_card;
    format.input = input_text_art;
    format.create_empty = make_empty_text_art_card;
    return format;
}
