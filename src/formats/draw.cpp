#include "draw.hpp"

#include "../render/screen.hpp"
#include "../text/buffer.hpp"

#include <string_view>

VisibleRowRange visible_rows(
    const Screen& screen,
    i32 top,
    i32 count
) {
    return {
        std::clamp(-top, 0, count),
        std::clamp(screen.height() - top, 0, count),
    };
}

void draw_box_outline(
    Screen& screen,
    Extent extent,
    CardId id,
    i32 x,
    i32 y,
    const CardFormat& format,
    CardVisualState state,
    PaintLayer layer
) {
    char32_t horizontal = format.horizontal;
    char32_t vertical = format.vertical;
    char32_t top_left = format.top_left;
    char32_t top_right = format.top_right;
    char32_t bottom_left = format.bottom_left;
    char32_t bottom_right = format.bottom_right;
    Style border_style = format.border;

    switch (state) {
        case CardVisualState::Normal:
            break;

        case CardVisualState::Hover:
            top_left = U'╭';
            top_right = U'╮';
            bottom_left = U'╰';
            bottom_right = U'╯';
            border_style = format.active_border;
            break;

        case CardVisualState::Selected:
            horizontal = U'═';
            vertical = U'║';
            top_left = U'╔';
            top_right = U'╗';
            bottom_left = U'╚';
            bottom_right = U'╝';
            border_style = format.active_border;
            break;

        case CardVisualState::Editing:
            horizontal = U'━';
            vertical = U'┃';
            top_left = U'┏';
            top_right = U'┓';
            bottom_left = U'┗';
            bottom_right = U'┛';
            border_style = format.active_border;
            break;
    }

    const DisplayRune horizontal_rune = display_rune(horizontal);
    const DisplayRune vertical_rune = display_rune(vertical);
    const DisplayRune top_left_rune = display_rune(top_left);
    const DisplayRune top_right_rune = display_rune(top_right);
    const DisplayRune bottom_left_rune = display_rune(bottom_left);
    const DisplayRune bottom_right_rune = display_rune(bottom_right);
    const i32 first_x = std::max(0, x + 1);
    const i32 last_x = std::min(
        screen.width(),
        x + extent.width - 1
    );
    const i32 first_y = std::max(0, y + 1);
    const i32 last_y = std::min(
        screen.height(),
        y + extent.height - 1
    );

    if (y >= 0 && y < screen.height()) {
        for (i32 screen_x = first_x; screen_x < last_x; ++screen_x) {
            screen.paint_layer(
                screen_x,
                y,
                horizontal_rune,
                border_style,
                id,
                layer
            );
        }
    }

    const i32 bottom = y + extent.height - 1;

    if (bottom >= 0 && bottom < screen.height() && bottom != y) {
        for (i32 screen_x = first_x; screen_x < last_x; ++screen_x) {
            screen.paint_layer(
                screen_x,
                bottom,
                horizontal_rune,
                border_style,
                id,
                layer
            );
        }
    }

    if (x >= 0 && x < screen.width()) {
        for (i32 screen_y = first_y; screen_y < last_y; ++screen_y) {
            screen.paint_layer(
                x,
                screen_y,
                vertical_rune,
                border_style,
                id,
                layer
            );
        }
    }

    const i32 right = x + extent.width - 1;

    if (right >= 0 && right < screen.width() && right != x) {
        for (i32 screen_y = first_y; screen_y < last_y; ++screen_y) {
            screen.paint_layer(
                right,
                screen_y,
                vertical_rune,
                border_style,
                id,
                layer
            );
        }
    }

    screen.paint_layer(
        x,
        y,
        top_left_rune,
        border_style,
        id,
        layer
    );
    screen.paint_layer(
        x + extent.width - 1,
        y,
        top_right_rune,
        border_style,
        id,
        layer
    );
    screen.paint_layer(
        x,
        y + extent.height - 1,
        bottom_left_rune,
        border_style,
        id,
        layer
    );
    screen.paint_layer(
        x + extent.width - 1,
        y + extent.height - 1,
        bottom_right_rune,
        border_style,
        id,
        layer
    );
}

void draw_box(
    Screen& screen,
    Extent extent,
    CardId id,
    i32 x,
    i32 y,
    const CardFormat& format,
    CardVisualState state
) {
    screen.fill(
        x,
        y,
        extent.width,
        extent.height,
        format.body,
        id
    );
    draw_box_outline(screen, extent, id, x, y, format, state);
}

i32 draw_string(
    Screen& screen,
    i32 left,
    i32 y,
    i32 width,
    std::string_view text,
    Style style,
    CardId owner
) {
    i32 cell = 0;

    for (u32 byte = 0; byte < text.size();) {
        const Rune rune = decode_utf8(text, byte);
        const DisplayRune display = display_rune(rune.codepoint);

        if (cell + display.width > width) {
            return cell;
        }

        screen.paint(
            left + cell,
            y,
            display,
            style,
            owner
        );

        cell += display.width;
        byte += rune.bytes;
    }

    return cell;
}
