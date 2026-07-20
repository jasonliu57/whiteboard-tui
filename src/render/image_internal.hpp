#pragma once

#include "font_rasterizer.hpp"
#include "screenshot.hpp"

#include <span>

struct ScreenshotColor {
    u8 red;
    u8 green;
    u8 blue;
};

ScreenshotColor screenshot_color(u8 index);

void fill_screenshot_rect(
    std::span<u8> pixels,
    u32 image_width,
    u32 image_height,
    i32 left,
    i32 top,
    i32 right,
    i32 bottom,
    ScreenshotColor color
);

void blend_screenshot_pixel(
    std::span<u8> pixels,
    u32 image_width,
    i32 x,
    i32 y,
    ScreenshotColor color,
    u8 alpha
);

void paint_screenshot_glyph(
    std::span<u8> pixels,
    u32 image_width,
    u32 image_height,
    FT_Face face,
    char32_t codepoint,
    Style style,
    i32 cell_x,
    i32 cell_y,
    i32 rune_width,
    i32 cell_width,
    i32 cell_height,
    i32 baseline
);

bool encode_screenshot_png(
    std::span<const u8> pixels,
    PngScreenshot& result
);
