#pragma once

#include "screen.hpp"

#include <string>
#include <string_view>
#include <cstddef>

struct PngScreenshot {
    std::string bytes;
    u32 width = 0;
    u32 height = 0;
};

std::string text_screenshot(
    const Screen& screen,
    std::string_view status
);

std::size_t text_screenshot_size(
    const Screen& screen,
    std::string_view status
);

void append_text_screenshot(
    std::string& output,
    const Screen& screen,
    std::string_view status
);

void append_text_screenshot(
    std::string& output,
    const Screen& screen,
    std::string_view status,
    std::size_t additional
);

bool png_screenshot(
    const Screen& screen,
    std::string_view status,
    u32 font_pixels,
    PngScreenshot& result
);
