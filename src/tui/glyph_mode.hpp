#pragma once

#include "tui.hpp"

#include <string_view>
#include <utility>

inline bool Tui::draw_glyph_text(std::string_view text) {
    const i64 line_x = board_cursor_.x;
    bool handled = false;
    bool invalid = false;
    glyph_writes_.clear();

    for (u32 byte = 0; byte < text.size();) {
        const u8 value = static_cast<u8>(text[byte]);

        if (value == '\r' || value == '\n') {
            if (
                value == '\r' &&
                byte + 1 < text.size() &&
                text[byte + 1] == '\n'
            ) {
                ++byte;
            }

            Pos next;

            if (!translate_glyph_position(
                    {line_x, board_cursor_.y},
                    {0, 1},
                    next
                )) {
                invalid = true;
                ++byte;
                continue;
            }

            board_cursor_ = next;
            ++byte;
            handled = true;
            continue;
        }

        if (value == '\t') {
            const i64 column = board_cursor_.x - line_x;
            Pos next;

            if (!translate_glyph_position(
                    board_cursor_,
                    {4 - column % 4, 0},
                    next
                )) {
                invalid = true;
                ++byte;
                continue;
            }

            board_cursor_ = next;
            ++byte;
            handled = true;
            continue;
        }

        const Rune rune = decode_utf8(text, byte);

        if (
            rune.codepoint == U' ' ||
            stored_glyph(rune.codepoint)
        ) {
            const i32 width = rune.codepoint == U' '
                ? 1
                : glyph_width(rune.codepoint);
            Pos next;

            if (
                !valid_glyph_position(board_cursor_, width) ||
                !translate_glyph_position(
                    board_cursor_,
                    {width, 0},
                    next
                )
            ) {
                byte += rune.bytes;
                invalid = true;
                continue;
            }

            glyph_writes_.push_back({
                board_cursor_,
                rune.codepoint,
            });
            board_cursor_ = next;
            byte += rune.bytes;
            handled = true;
            continue;
        }

        byte += rune.bytes;
        invalid = true;
    }

    const bool changed = app_.write_glyphs(glyph_writes_);
    keep_board_cursor_visible();

    if (invalid) {
        message_ = "glyph must occupy one or two cells";
    } else if (changed) {
        message_ = "glyph written";
    } else if (handled) {
        message_.clear();
    }

    return handled || invalid;
}

inline void Tui::begin_glyph_mode() {
    if (board_mode_ != BoardMode::Cursor) {
        message_ = "leave selection before GLYPH mode";
        return;
    }

    board_mode_ = BoardMode::Glyph;
    reset_glyph_mode_state(glyph_mode_);
    glyph_mode_.anchor = board_cursor_;
    message_ = "GLYPH draw";
}

inline void Tui::leave_glyph_mode() {
    board_mode_ = BoardMode::Cursor;
    reset_glyph_mode_state(glyph_mode_);
    keep_board_cursor_visible();
    message_ = "board mode";
}

inline void Tui::toggle_glyph_selection() {
    if (glyph_mode_.phase == GlyphPhase::Draw) {
        glyph_mode_.phase = GlyphPhase::Select;
        glyph_mode_.anchor = board_cursor_;
        message_ = "GLYPH selection anchor";
    } else {
        glyph_mode_.phase = GlyphPhase::Draw;
        glyph_mode_.anchor = board_cursor_;
        message_ = "GLYPH draw";
    }
}

inline void Tui::move_glyph_viewport(i64 dx, i64 dy) {
    if (!move_viewport(dx, dy)) {
        return;
    }

    if (glyph_mode_.phase != GlyphPhase::Draw) {
        Pos moved;

        if (checked_translate(glyph_mode_.anchor, {dx, dy}, moved)) {
            glyph_mode_.anchor = moved;
        }
    }

    if (glyph_mode_.phase == GlyphPhase::Place) {
        Pos moved;

        if (checked_translate(
                glyph_mode_.placement.delta,
                {dx, dy},
                moved
            )) {
            glyph_mode_.placement.delta = moved;
        }
    }
}

inline void Tui::select_glyph_corner(i64 dx, i64 dy) {
    const Rect frame = selection_rect(
        glyph_mode_.anchor,
        board_cursor_
    );
    Pos cursor = board_cursor_;

    if (dx < 0) {
        cursor.x = frame.left;
    } else if (dx > 0) {
        cursor.x = frame.right - 1;
    } else if (dy < 0) {
        cursor.y = frame.top;
    } else {
        cursor.y = frame.bottom - 1;
    }

    glyph_mode_.anchor = {
        cursor.x == frame.left
            ? frame.right - 1
            : frame.left,
        cursor.y == frame.top
            ? frame.bottom - 1
            : frame.top,
    };
    board_cursor_ = cursor;
    keep_board_cursor_visible();
    message_ = "glyph selection corner";
}

inline void Tui::begin_glyph_placement(i64 dx, i64 dy) {
    GlyphPlacement& placement = glyph_mode_.placement;
    clear_glyph_placement(placement);
    placement.source = selection_rect(
        glyph_mode_.anchor,
        board_cursor_
    );
    placement.original_anchor = glyph_mode_.anchor;
    placement.original_cursor = board_cursor_;

    if (!app_.collect_glyphs(
            placement.source,
            placement.cells
        )) {
        clear_glyph_placement(placement);
        message_ = "glyph selection empty";
        return;
    }

    Pos anchor;
    Pos cursor;

    if (
        !translate_glyph_position(
            glyph_mode_.anchor,
            {dx, dy},
            anchor
        ) ||
        !translate_glyph_position(
            board_cursor_,
            {dx, dy},
            cursor
        )
    ) {
        clear_glyph_placement(placement);
        message_ = "glyph placement outside coordinate range";
        return;
    }

    placement.delta = {dx, dy};
    glyph_mode_.phase = GlyphPhase::Place;
    glyph_mode_.anchor = anchor;
    board_cursor_ = cursor;
    keep_board_cursor_visible();
    message_ = "glyph placement preview";
}

inline void Tui::move_glyph_placement(i64 dx, i64 dy) {
    Pos anchor;
    Pos cursor;
    Pos delta;

    if (
        !translate_glyph_position(
            glyph_mode_.anchor,
            {dx, dy},
            anchor
        ) ||
        !translate_glyph_position(
            board_cursor_,
            {dx, dy},
            cursor
        ) ||
        !translate_glyph_position(
            glyph_mode_.placement.delta,
            {dx, dy},
            delta
        )
    ) {
        message_ = "glyph placement outside coordinate range";
        return;
    }

    glyph_mode_.anchor = anchor;
    glyph_mode_.placement.delta = delta;
    board_cursor_ = cursor;
    keep_board_cursor_visible();
    message_ = "glyph placement preview";
}

inline void Tui::commit_glyph_placement() {
    if (
        glyph_mode_.placement.delta.x == 0 &&
        glyph_mode_.placement.delta.y == 0
    ) {
        cancel_glyph_placement();
        message_ = "glyph placement unchanged";
        return;
    }

    if (!app_.place_glyphs(
            glyph_mode_.placement.cells,
            glyph_mode_.placement.delta
        )) {
        message_ = "glyph placement outside coordinate range";
        return;
    }

    glyph_mode_.phase = GlyphPhase::Select;
    clear_glyph_placement(glyph_mode_.placement);
    message_ = "glyph selection placed";
}

inline void Tui::cancel_glyph_placement() {
    glyph_mode_.anchor =
        glyph_mode_.placement.original_anchor;
    board_cursor_ = glyph_mode_.placement.original_cursor;
    glyph_mode_.phase = GlyphPhase::Select;
    clear_glyph_placement(glyph_mode_.placement);
    keep_board_cursor_visible();
    message_ = "glyph placement canceled";
}

inline void Tui::convert_glyph_card() {
    Card card;

    switch (make_text_art_card(
        app_.glyphs,
        selection_rect(glyph_mode_.anchor, board_cursor_),
        glyph_writes_,
        card
    )) {
        case TextArtBuildResult::Success:
            break;

        case TextArtBuildResult::Empty:
            message_ = "glyph selection empty";
            return;

        case TextArtBuildResult::TooLarge:
            message_ = "glyph selection too large for text-art";
            return;
    }

    const CardId id = app_.replace_glyphs_with_card(
        std::move(card),
        glyph_writes_
    );
    reset_glyph_mode_state(glyph_mode_);
    finish_card_creation(id);
    message_ = "text-art created; source glyphs removed; undo cleared";
}

inline void Tui::convert_text_art_glyphs() {
    const CardId id = selected_card_;
    const Card& card = app_.board.get(id);

    if (card.static_format != kTextArtStaticFormatId) {
        message_ = "selected card is not text-art";
        return;
    }

    switch (make_text_art_glyphs(card, glyph_writes_)) {
        case TextArtGlyphResult::Success:
            break;

        case TextArtGlyphResult::UnsupportedGlyph:
            message_ = "text-art contains unsupported glyph";
            return;

        case TextArtGlyphResult::OutsideCoordinateRange:
            message_ = "text-art outside glyph coordinate range";
            return;
    }

    const Rect footprint = app_.spatial.slots[id].rect;
    app_.replace_card_with_glyphs(
        id,
        footprint,
        glyph_writes_
    );

    selected_card_ = kNoCard;
    board_mode_ = BoardMode::Glyph;
    reset_glyph_mode_state(glyph_mode_);
    glyph_mode_.phase = GlyphPhase::Select;
    glyph_mode_.anchor = {footprint.left, footprint.top};
    board_cursor_ = {
        footprint.right - 1,
        footprint.bottom - 1,
    };
    message_ = "text-art converted to glyphs; undo cleared";
}

inline void Tui::copy_glyphs() {
    if (glyph_mode_.phase == GlyphPhase::Draw) {
        message_ = app_.copy_glyph(board_cursor_)
            ? "glyph copied"
            : "no glyph";
    } else if (glyph_mode_.phase == GlyphPhase::Select) {
        message_ = app_.copy_glyphs(selection_rect(
            glyph_mode_.anchor,
            board_cursor_
        ))
            ? "glyph selection copied"
            : "glyph selection empty";
    } else {
        message_ = "Enter place, Esc cancel";
    }
}

inline void Tui::cut_glyph_selection() {
    if (glyph_mode_.phase != GlyphPhase::Select) {
        message_ = "select glyphs before cutting";
        return;
    }

    message_ = app_.cut_glyphs(selection_rect(
        glyph_mode_.anchor,
        board_cursor_
    ))
        ? "glyph selection cut"
        : "glyph selection empty";
}

inline void Tui::paste_glyph_clipboard() {
    message_ = app_.paste_glyphs(board_cursor_)
        ? "glyph clipboard pasted"
        : "glyph clipboard empty or outside coordinate range";
}

inline void Tui::erase_glyph_at_cursor() {
    message_ = app_.set_glyph(board_cursor_, ' ')
        ? "glyph erased"
        : "no glyph";
}

inline void Tui::erase_glyph_selection() {
    message_ = app_.erase_glyphs(
        selection_rect(glyph_mode_.anchor, board_cursor_)
    )
        ? "glyph selection erased"
        : "glyph selection empty";
}
