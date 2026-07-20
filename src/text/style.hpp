#pragma once

#include "../model.hpp"
#include "buffer.hpp"

#include <cstddef>

struct TextStyleChange {
    u32 current_first_row = 0;
    u32 current_last_row = 0;
    u32 replacement_first_row = 0;
    u32 replacement_last_row = 0;
    TextStyles replacement;
};

struct TextStyleCursor {
    std::size_t row = 0;
    std::size_t span = 0;
};

void apply_text_span(TextStyles& styles, TextSpan applied);

void canonicalize_text_styles(
    TextStyles& styles,
    const TextLines& lines
);

void canonicalize_text_styles(TextCardData& data);

TextStyleCursor text_style_index(
    const TextStyles& styles,
    u32 row,
    u32 byte
);

TextStyles text_style_rows(
    const TextStyles& styles,
    u32 first_row,
    u32 last_row
);

void replace_text_style_rows(
    TextStyles& styles,
    u32 first_row,
    u32 last_row,
    const TextStyles& replacement
);

TextPos map_text_position_after_edit(
    const TextEdit& edit,
    TextPos position
);

void edit_text_styles(TextStyles& styles, const TextEdit& edit);
