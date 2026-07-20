#pragma once

#include "../glyph_layer.hpp"
#include "../spatial/board_spatial.hpp"

// Shared geometry for native thumbnails and browser overviews. No image, font,
// document ownership or renderer state lives here. Glyphs are optional for the
// native thumbnail's existing card/edge contract.
bool board_overview_bounds(const Board& board, const CardSpatial& spatial,
                           Rect& bounds, const GlyphLayer* glyphs = nullptr);

struct BoardProjection {
    Rect bounds{};
    long double scale = 1;
    i32 margin = 16;

    static long double distance(i64 value, i64 origin);
    long double offset(i64 value, i64 origin) const;
    i32 floor(i64 value, i64 origin) const;
    i32 ceil(i64 value, i64 origin) const;
    i32 point(i64 value, i64 origin) const;
    double x(i64 value) const;
    double y(i64 value) const;
    Pos world(double x, double y) const; // finite [0, 1], within half-open bounds
};
