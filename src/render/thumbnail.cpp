#include "thumbnail.hpp"
#include "image_internal.hpp"
#include "overview.hpp"

#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <limits>
#include <memory>
#include <new>
#include <string_view>

static void draw_thumbnail_edge(
    std::span<u8> pixels,
    u32 image_width,
    u32 image_height,
    Pos first,
    Pos second,
    const BoardProjection& projection,
    ScreenshotColor color
) {
    const i32 first_x = projection.point(first.x, projection.bounds.left);
    const i32 first_y = projection.point(first.y, projection.bounds.top);
    const i32 second_x = projection.point(second.x, projection.bounds.left);
    const i32 second_y = projection.point(second.y, projection.bounds.top);

    if (first.y == second.y) {
        fill_screenshot_rect(
            pixels,
            image_width,
            image_height,
            std::min(first_x, second_x),
            first_y,
            std::max(first_x, second_x) + 1,
            first_y + 1,
            color
        );
    } else {
        fill_screenshot_rect(
            pixels,
            image_width,
            image_height,
            first_x,
            std::min(first_y, second_y),
            first_x + 1,
            std::max(first_y, second_y) + 1,
            color
        );
    }
}

static std::string_view thumbnail_card_label(
    CardId id,
    const Card& card,
    const CardFormats& formats,
    BoardThumbnailLabel label,
    std::array<
        char,
        std::numeric_limits<CardId>::digits10 + 1
    >& buffer
) {
    if (label == BoardThumbnailLabel::CardId) {
        const auto result = std::to_chars(
            buffer.data(),
            buffer.data() + buffer.size(),
            id
        );
        return {
            buffer.data(),
            static_cast<std::size_t>(result.ptr - buffer.data())
        };
    }

    if (label == BoardThumbnailLabel::Name) {
        const std::string_view name = card_name(card);

        if (!name.empty()) {
            return name;
        }
    }

    return formats[card.static_format].name;
}

static void draw_thumbnail_label(
    std::span<u8> pixels,
    u32 image_width,
    u32 image_height,
    FT_Face face,
    std::string_view text,
    i32 left,
    i32 top,
    i32 right,
    i32 bottom,
    i32 cell_width,
    i32 cell_height,
    i32 baseline
) {
    constexpr i32 padding = 2;
    const i32 column =
        (left + padding + cell_width - 1) / cell_width;
    const i32 row =
        (top + padding + cell_height - 1) / cell_height;
    const i32 end_column = (right - padding) / cell_width;

    if (
        column >= end_column ||
        (row + 1) * cell_height > bottom - padding
    ) {
        return;
    }

    i32 current = column;

    for (u32 byte = 0; byte < text.size();) {
        const Rune rune = decode_utf8(text, byte);
        const DisplayRune display = display_rune(rune.codepoint);

        if (current + display.width > end_column) {
            break;
        }

        paint_screenshot_glyph(
            pixels,
            image_width,
            image_height,
            face,
            display.glyph,
            Style{15, 0, AttrNone},
            current,
            row,
            display.width,
            cell_width,
            cell_height,
            baseline
        );
        current += display.width;
        byte += rune.bytes;
    }
}

static void blend_thumbnail_rect(
    std::span<u8> pixels,
    u32 image_width,
    u32 image_height,
    i32 left,
    i32 top,
    i32 right,
    i32 bottom,
    ScreenshotColor color,
    u8 alpha
) {
    left = std::max<i32>(left, 0);
    top = std::max<i32>(top, 0);
    right = std::min<i32>(right, image_width);
    bottom = std::min<i32>(bottom, image_height);

    for (i32 y = top; y < bottom; ++y) {
        for (i32 x = left; x < right; ++x) {
            blend_screenshot_pixel(
                pixels,
                image_width,
                x,
                y,
                color,
                alpha
            );
        }
    }
}

static void draw_thumbnail_viewport(
    std::span<u8> pixels,
    u32 image_width,
    u32 image_height,
    Rect viewport,
    const BoardProjection& projection
) {
    const Rect bounds = projection.bounds;

    if (!overlaps(viewport, bounds)) {
        return;
    }

    const Rect clipped{
        std::max(viewport.left, bounds.left),
        std::max(viewport.top, bounds.top),
        std::min(viewport.right, bounds.right),
        std::min(viewport.bottom, bounds.bottom),
    };
    const i32 left = projection.floor(clipped.left, bounds.left);
    const i32 top = projection.floor(clipped.top, bounds.top);
    const i32 right = projection.ceil(clipped.right, bounds.left);
    const i32 bottom = projection.ceil(clipped.bottom, bounds.top);
    constexpr ScreenshotColor color{0, 205, 220};
    constexpr i32 thickness = 2;

    blend_thumbnail_rect(
        pixels,
        image_width,
        image_height,
        left,
        top,
        right,
        bottom,
        color,
        24
    );

    if (viewport.top >= bounds.top) {
        fill_screenshot_rect(
            pixels,
            image_width,
            image_height,
            left,
            top,
            right,
            std::min(top + thickness, bottom),
            color
        );
    }

    if (viewport.right <= bounds.right) {
        fill_screenshot_rect(
            pixels,
            image_width,
            image_height,
            std::max(left, right - thickness),
            top,
            right,
            bottom,
            color
        );
    }

    if (viewport.bottom <= bounds.bottom) {
        fill_screenshot_rect(
            pixels,
            image_width,
            image_height,
            left,
            std::max(top, bottom - thickness),
            right,
            bottom,
            color
        );
    }

    if (viewport.left >= bounds.left) {
        fill_screenshot_rect(
            pixels,
            image_width,
            image_height,
            left,
            top,
            std::min(left + thickness, right),
            bottom,
            color
        );
    }
}

BoardThumbnailResult board_thumbnail_png(
    const Board& board,
    const CardSpatial& spatial,
    const CardFormats& formats,
    u32 max_side,
    BoardThumbnailLabel label,
    const Rect* viewport,
    PngScreenshot& result
) {
    result = PngScreenshot{};
    Rect bounds;

    if (
        max_side < kBoardThumbnailMinimumSide ||
        max_side > kBoardThumbnailMaximumSide
    ) {
        return BoardThumbnailResult::Failed;
    }

    if (!board_overview_bounds(board, spatial, bounds)) {
        return BoardThumbnailResult::Empty;
    }

    constexpr i32 margin = 16;
    const long double world_width =
        BoardProjection::distance(bounds.right, bounds.left);
    const long double world_height =
        BoardProjection::distance(bounds.bottom, bounds.top);
    const long double content_side = max_side - 2 * margin;
    BoardProjection projection{
        .bounds = bounds,
        .scale = content_side / std::max(world_width, world_height),
        .margin = margin,
    };
    result.width = std::min<u32>(
        max_side,
        static_cast<u32>(std::ceil(
            world_width * projection.scale
        )) + 2 * margin
    );
    result.height = std::min<u32>(
        max_side,
        static_cast<u32>(std::ceil(
            world_height * projection.scale
        )) + 2 * margin
    );
    const std::size_t pixel_bytes =
        static_cast<std::size_t>(result.width) * result.height * 4;
    std::unique_ptr<u8[]> pixel_storage;

    try {
        pixel_storage = std::make_unique_for_overwrite<u8[]>(pixel_bytes);
    } catch (const std::bad_alloc&) {
        return BoardThumbnailResult::Failed;
    }

    std::span<u8> pixels{pixel_storage.get(), pixel_bytes};
    fill_screenshot_rect(
        pixels,
        result.width,
        result.height,
        0,
        0,
        result.width,
        result.height,
        {18, 20, 24}
    );

    for (EdgeId id = 0; id < board.edges.size(); ++id) {
        const Edge* edge = board.find_edge(id);

        if (
            edge == nullptr ||
            board.find(edge->source.card) == nullptr ||
            board.find(edge->target.card) == nullptr
        ) {
            continue;
        }

        const ScreenshotColor color =
            edge->state == RouteState::Ready
                ? ScreenshotColor{96, 110, 126}
                : ScreenshotColor{205, 48, 48};

        for (u32 point = 0;
             point + 1 < edge->points.size();
             ++point) {
            draw_thumbnail_edge(
                pixels,
                result.width,
                result.height,
                edge->points[point],
                edge->points[point + 1],
                projection,
                color
            );
        }
    }

    const u32 font_pixels = std::clamp<u32>(
        max_side / 100,
        8,
        20
    );
    FontRasterizer font;

    if (!font.open_default(font_pixels)) {
        return BoardThumbnailResult::Failed;
    }

    const FT_Face face = font.face();
    const i32 cell_width = font.cell_width();
    const i32 cell_height = font.cell_height();
    const i32 baseline = font.baseline();
    std::array<
        char,
        std::numeric_limits<CardId>::digits10 + 1
    > label_buffer;

    for (CardId id = 0; id < board.cards.size(); ++id) {
        const Card* card = board.find(id);

        if (card == nullptr) {
            continue;
        }

        const Rect rect = spatial.slots[id].rect;
        const i32 left = projection.floor(rect.left, bounds.left);
        const i32 top = projection.floor(rect.top, bounds.top);
        const i32 right = std::max(
            left + 1,
            projection.ceil(rect.right, bounds.left)
        );
        const i32 bottom = std::max(
            top + 1,
            projection.ceil(rect.bottom, bounds.top)
        );
        const ScreenshotColor border = screenshot_color(
            static_cast<u8>(8 + card->static_format % 8)
        );
        fill_screenshot_rect(
            pixels,
            result.width,
            result.height,
            left,
            top,
            right,
            bottom,
            {38, 42, 50}
        );
        fill_screenshot_rect(
            pixels,
            result.width,
            result.height,
            left,
            top,
            right,
            top + 1,
            border
        );
        fill_screenshot_rect(
            pixels,
            result.width,
            result.height,
            left,
            bottom - 1,
            right,
            bottom,
            border
        );
        fill_screenshot_rect(
            pixels,
            result.width,
            result.height,
            left,
            top,
            left + 1,
            bottom,
            border
        );
        fill_screenshot_rect(
            pixels,
            result.width,
            result.height,
            right - 1,
            top,
            right,
            bottom,
            border
        );
        draw_thumbnail_label(
            pixels,
            result.width,
            result.height,
            face,
            thumbnail_card_label(
                id,
                *card,
                formats,
                label,
                label_buffer
            ),
            left,
            top,
            right,
            bottom,
            cell_width,
            cell_height,
            baseline
        );
    }

    if (viewport != nullptr) {
        draw_thumbnail_viewport(
            pixels,
            result.width,
            result.height,
            *viewport,
            projection
        );
    }

    return encode_screenshot_png(pixels, result)
        ? BoardThumbnailResult::Success
        : BoardThumbnailResult::Failed;
}
