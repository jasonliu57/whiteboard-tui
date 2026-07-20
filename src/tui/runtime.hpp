#pragma once

#include "tui.hpp"
#include <algorithm>
#include <span>
#include <utility>

inline Tui::Tui(i32 width, i32 height, std::string name, TuiHost host)
    : host_(host), app_(width, std::max<i32>(1, height - 1)),
      viewport_{0, 0, width, std::max<i32>(1, height - 1)},
      main_file_(std::move(name)), message_("new board") {}

inline void Tui::resize(i32 width, i32 height, bool follow_cursor) {
    const i32 board_height = std::max<i32>(1, height - 1);

    app_.resize_screen(width, board_height);
    viewport_.width = width;
    viewport_.height = board_height;

    if (follow_cursor && board_mode_ != BoardMode::Select) {
        keep_board_cursor_visible();
    }

    if (board_mode_ == BoardMode::Edge) {
        update_edge_preview();
    }
}

inline void Tui::render() {
    const Rect visible = viewport_rect(viewport_);
    frame_hovered_ = card_under_cursor();
    const bool cursor_visible =
        app_.session.active == kNoCard &&
        board_mode_ != BoardMode::Select;
    const EdgePoints* edge_preview =
        board_mode_ == BoardMode::Edge &&
        edge_mode_.phase != EdgePhase::Browse &&
        !edge_mode_.prepared.points.empty()
            ? &edge_mode_.prepared.points
            : nullptr;
    const bool placing_glyphs =
        board_mode_ == BoardMode::Glyph &&
        glyph_mode_.phase == GlyphPhase::Place;

    app_.render(
        viewport_,
        visible,
        board_mode_ == BoardMode::Cursor
            ? frame_hovered_
            : kNoCard,
        board_mode_ == BoardMode::Select
            ? selected_card_
            : kNoCard,
        board_mode_ == BoardMode::Edge
            ? edge_mode_.selected
            : kNoEdge,
        edge_preview,
        edge_mode_.preview_valid,
        placing_glyphs
            ? &glyph_mode_.placement.source
            : nullptr,
        placing_glyphs
            ? std::span<const GlyphCell>{glyph_mode_.placement.cells}
            : std::span<const GlyphCell>{},
        placing_glyphs
            ? glyph_mode_.placement.delta
            : Pos{}
    );

    if (host_.overlay) host_.overlay(host_.context, visible);

    if (
        board_mode_ == BoardMode::Glyph &&
        glyph_mode_.phase == GlyphPhase::Select
    ) {
        app_.render_glyph_selection(
            viewport_,
            visible,
            selection_rect(glyph_mode_.anchor, board_cursor_)
        );
    }

    if (cursor_visible) {
        app_.screen.invert(
            static_cast<i32>(board_cursor_.x - viewport_.x),
            static_cast<i32>(board_cursor_.y - viewport_.y)
        );
    }
}
