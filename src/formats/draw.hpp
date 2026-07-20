#pragma once

#include "format.hpp"
#include "../render/screen.hpp"

#include <string_view>

struct VisibleRowRange {
    i32 first = 0;
    i32 last = 0;
};

VisibleRowRange visible_rows(
    const Screen& screen,
    i32 top,
    i32 count
);

void draw_box_outline(
    Screen& screen,
    Extent extent,
    CardId id,
    i32 x,
    i32 y,
    const CardFormat& format,
    CardVisualState state,
    PaintLayer layer = PaintLayer::Card
);

void draw_box(
    Screen& screen,
    Extent extent,
    CardId id,
    i32 x,
    i32 y,
    const CardFormat& format,
    CardVisualState state
);

i32 draw_string(
    Screen& screen,
    i32 left,
    i32 y,
    i32 width,
    std::string_view text,
    Style style,
    CardId owner
);
