#pragma once

#include "../board.hpp"
#include "../formats/format.hpp"
#include "../glyph_layer.hpp"
#include "../spatial/board_spatial.hpp"
#include "screen.hpp"

#include <span>
#include <vector>

void render_board(
    Screen& screen,
    const Board& board,
    const CardSpatial& spatial,
    const EdgeSpatial& edge_spatial,
    const GlyphLayer& glyphs,
    const Viewport& view,
    Rect visible,
    const CardFormats& formats,
    const CardSession& session,
    CardId hovered,
    CardId selected,
    EdgeId selected_edge,
    const EdgePoints* edge_preview,
    bool edge_preview_valid,
    const Rect* hidden_glyphs,
    const std::vector<GlyphCell>* glyph_preview,
    Pos glyph_preview_delta
);

void render_board_span(
    Screen& screen,
    const Board& board,
    const CardSpatial& spatial,
    const EdgeSpatial& edge_spatial,
    const GlyphLayer& glyphs,
    const Viewport& view,
    Rect visible,
    const CardFormats& formats,
    const CardSession& session,
    CardId hovered,
    CardId selected,
    EdgeId selected_edge,
    const EdgePoints* edge_preview,
    bool edge_preview_valid,
    const Rect* hidden_glyphs,
    std::span<const GlyphCell> glyph_preview,
    Pos glyph_preview_delta
);

void draw_world_outline(
    Screen& screen,
    Rect rect,
    const Viewport& view,
    Rect visible,
    char32_t glyph,
    Style style
);
