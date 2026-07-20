#include "screenshot.hpp"
#include "image_internal.hpp"

#include "font_rasterizer.hpp"
#include "../text/utf8.hpp"

#include <algorithm>
#include <array>
#include <limits>
#include <memory>
#include <new>
#include <stdexcept>
#include <string>
#include <string_view>

#include <png.h>

static std::size_t utf8_encoded_size(char32_t codepoint) noexcept {
    if (codepoint <= 0x7F) {
        return 1;
    }

    if (codepoint <= 0x7FF) {
        return 2;
    }

    return codepoint <= 0xFFFF ? 3 : 4;
}

template<class Emit>
static void emit_screenshot_text(
    const Screen& screen,
    std::string_view status,
    Emit&& emit
) {
    for (i32 y = 0; y < screen.height(); ++y) {
        for (i32 x = 0; x < screen.width(); ++x) {
            const ScreenCell& cell = screen.at(x, y);

            if (cell.width != 0) {
                emit(cell.glyph);

                for (char32_t mark : cell.combining) {
                    emit(mark);
                }
            }
        }

        emit(U'\n');
    }

    i32 cell = 0;

    for (u32 byte = 0;
         byte < status.size() && cell < screen.width();) {
        const Rune rune = decode_utf8(status, byte);
        const DisplayRune display = display_rune(rune.codepoint);

        if (cell + display.width > screen.width()) {
            break;
        }

        emit(display.glyph);
        cell += display.width;
        byte += rune.bytes;
    }

    while (cell < screen.width()) {
        emit(U' ');
        ++cell;
    }

    emit(U'\n');
}

std::size_t text_screenshot_size(
    const Screen& screen,
    std::string_view status
) {
    std::size_t size = 0;
    emit_screenshot_text(
        screen,
        status,
        [&](char32_t codepoint) {
            size += utf8_encoded_size(codepoint);
        }
    );
    return size;
}

void append_text_screenshot(
    std::string& output,
    const Screen& screen,
    std::string_view status
) {
    append_text_screenshot(
        output,
        screen,
        status,
        text_screenshot_size(screen, status)
    );
}

void append_text_screenshot(
    std::string& output,
    const Screen& screen,
    std::string_view status,
    std::size_t additional
) {
    if (additional > output.max_size() - output.size()) {
        throw std::length_error{"text screenshot exceeds string capacity"};
    }

    output.reserve(output.size() + additional);
    emit_screenshot_text(
        screen,
        status,
        [&](char32_t codepoint) {
            append_utf8(output, codepoint);
        }
    );
}

std::string text_screenshot(
    const Screen& screen,
    std::string_view status
) {
    std::string output;
    append_text_screenshot(
        output,
        screen,
        status,
        text_screenshot_size(screen, status)
    );
    return output;
}

static constexpr std::array<ScreenshotColor, 16> kScreenshotPalette{{
    {0, 0, 0},
    {205, 0, 0},
    {0, 205, 0},
    {205, 205, 0},
    {0, 0, 238},
    {205, 0, 205},
    {0, 205, 205},
    {229, 229, 229},
    {127, 127, 127},
    {255, 0, 0},
    {0, 255, 0},
    {255, 255, 0},
    {92, 92, 255},
    {255, 0, 255},
    {0, 255, 255},
    {255, 255, 255},
}};

ScreenshotColor screenshot_color(u8 index) {
    return kScreenshotPalette[std::min<u8>(index, 15)];
}

void fill_screenshot_rect(
    std::span<u8> pixels,
    u32 image_width,
    u32 image_height,
    i32 left,
    i32 top,
    i32 right,
    i32 bottom,
    ScreenshotColor color
) {
    left = std::max<i32>(left, 0);
    top = std::max<i32>(top, 0);
    right = std::min<i32>(right, image_width);
    bottom = std::min<i32>(bottom, image_height);

    if (left >= right || top >= bottom) {
        return;
    }

    for (i32 y = top; y < bottom; ++y) {
        u8* pixel = pixels.data() +
            (static_cast<std::size_t>(y) * image_width + left) * 4;

        for (i32 x = left; x < right; ++x) {
            pixel[0] = color.red;
            pixel[1] = color.green;
            pixel[2] = color.blue;
            pixel[3] = 255;
            pixel += 4;
        }
    }
}

void blend_screenshot_pixel(
    std::span<u8> pixels,
    u32 image_width,
    i32 x,
    i32 y,
    ScreenshotColor color,
    u8 alpha
) {
    const std::size_t offset =
        (static_cast<std::size_t>(y) * image_width + x) * 4;
    const u32 inverse = 255 - alpha;
    pixels[offset] = static_cast<u8>(
        (color.red * alpha + pixels[offset] * inverse) / 255
    );
    pixels[offset + 1] = static_cast<u8>(
        (color.green * alpha + pixels[offset + 1] * inverse) / 255
    );
    pixels[offset + 2] = static_cast<u8>(
        (color.blue * alpha + pixels[offset + 2] * inverse) / 255
    );
}

void paint_screenshot_glyph(
    std::span<u8> pixels,
    u32 image_width,
    u32 image_height,
    FT_Face face,
    char32_t glyph,
    Style style,
    i32 column,
    i32 row,
    i32 cells,
    i32 cell_width,
    i32 cell_height,
    i32 baseline
) {
    const i32 clip_left = column * cell_width;
    const i32 clip_top = row * cell_height;
    const i32 clip_right = std::min<i32>(
        image_width,
        clip_left + cells * cell_width
    );
    const i32 clip_bottom = std::min<i32>(
        image_height,
        clip_top + cell_height
    );
    const ScreenshotColor foreground =
        screenshot_color(style.foreground);

    if (
        glyph != U' ' &&
        FT_Load_Char(face, glyph, FT_LOAD_RENDER) == 0
    ) {
        const FT_GlyphSlot slot = face->glyph;
        const FT_Bitmap& bitmap = slot->bitmap;
        const i32 advance = static_cast<i32>(slot->advance.x >> 6);
        const i32 origin_x = clip_left +
            (cells * cell_width - advance) / 2 + slot->bitmap_left;
        const i32 origin_y = clip_top + baseline - slot->bitmap_top;
        const i32 passes =
            (style.attributes & AttrBold) != 0 ? 2 : 1;

        for (i32 pass = 0; pass < passes; ++pass) {
            for (u32 bitmap_y = 0;
                 bitmap_y < bitmap.rows;
                 ++bitmap_y) {
                const i32 y = origin_y + bitmap_y;

                if (y < clip_top || y >= clip_bottom) {
                    continue;
                }

                const u8* source = bitmap.pitch >= 0
                    ? bitmap.buffer + bitmap_y * bitmap.pitch
                    : bitmap.buffer +
                        (bitmap.rows - 1 - bitmap_y) * -bitmap.pitch;

                for (u32 bitmap_x = 0;
                     bitmap_x < bitmap.width;
                     ++bitmap_x) {
                    const i32 x = origin_x + bitmap_x + pass;

                    if (x < clip_left || x >= clip_right) {
                        continue;
                    }

                    u8 alpha = 0;

                    if (bitmap.pixel_mode == FT_PIXEL_MODE_GRAY) {
                        alpha = source[bitmap_x];
                    } else if (bitmap.pixel_mode == FT_PIXEL_MODE_MONO) {
                        alpha = (source[bitmap_x / 8] &
                            (0x80 >> (bitmap_x % 8))) != 0
                            ? 255
                            : 0;
                    }

                    if (alpha != 0) {
                        blend_screenshot_pixel(
                            pixels,
                            image_width,
                            x,
                            y,
                            foreground,
                            alpha
                        );
                    }
                }
            }
        }
    }

    if ((style.attributes & AttrUnderline) != 0) {
        const i32 underline = std::min(
            clip_bottom - 1,
            clip_top + baseline + 1
        );
        fill_screenshot_rect(
            pixels,
            image_width,
            image_height,
            clip_left,
            underline,
            clip_right,
            underline + 1,
            foreground
        );
    }
}

bool encode_screenshot_png(
    std::span<const u8> pixels,
    PngScreenshot& result
) {
    png_image image{};
    image.version = PNG_IMAGE_VERSION;
    image.width = result.width;
    image.height = result.height;
    image.format = PNG_FORMAT_RGBA;
    png_alloc_size_t size = 0;

    if (!png_image_write_to_memory(
            &image,
            nullptr,
            &size,
            0,
            pixels.data(),
            0,
            nullptr
        )) {
        png_image_free(&image);
        return false;
    }

    try {
        result.bytes.resize(size);
    } catch (const std::bad_alloc&) {
        png_image_free(&image);
        return false;
    } catch (const std::length_error&) {
        png_image_free(&image);
        return false;
    }

    if (!png_image_write_to_memory(
            &image,
            result.bytes.data(),
            &size,
            0,
            pixels.data(),
            0,
            nullptr
        )) {
        result.bytes.clear();
        png_image_free(&image);
        return false;
    }

    result.bytes.resize(size);
    png_image_free(&image);
    return true;
}

static bool render_png_screenshot(
    const Screen& screen,
    std::string_view status,
    const FontRasterizer& font,
    PngScreenshot& result
) {
    const FT_Face face = font.face();
    const i32 cell_width = font.cell_width();
    const i32 cell_height = font.cell_height();
    const i32 baseline = font.baseline();
    const u64 pixel_width =
        static_cast<u64>(screen.width()) * cell_width;
    const u64 pixel_height =
        (static_cast<u64>(screen.height()) + 1) * cell_height;
    constexpr u64 kMaximumRgbaBytes = 256ULL * 1024ULL * 1024ULL;

    if (
        pixel_width == 0 || pixel_height == 0 ||
        pixel_width > std::numeric_limits<i32>::max() ||
        pixel_height > std::numeric_limits<i32>::max() ||
        pixel_height >
            std::numeric_limits<std::size_t>::max() / 4 / pixel_width ||
        pixel_height > kMaximumRgbaBytes / 4 / pixel_width
    ) {
        return false;
    }

    result.width = static_cast<u32>(pixel_width);
    result.height = static_cast<u32>(pixel_height);
    const std::size_t pixel_bytes =
        static_cast<std::size_t>(pixel_width * pixel_height * 4);
    std::unique_ptr<u8[]> pixel_storage;

    try {
        pixel_storage = std::make_unique_for_overwrite<u8[]>(pixel_bytes);
    } catch (const std::bad_alloc&) {
        return false;
    }

    std::span<u8> pixels{pixel_storage.get(), pixel_bytes};

    for (i32 y = 0; y < screen.height(); ++y) {
        for (i32 x = 0; x < screen.width(); ++x) {
            fill_screenshot_rect(
                pixels,
                result.width,
                result.height,
                x * cell_width,
                y * cell_height,
                (x + 1) * cell_width,
                (y + 1) * cell_height,
                screenshot_color(screen.at(x, y).style.background)
            );
        }
    }

    const i32 status_row = screen.height();
    fill_screenshot_rect(
        pixels,
        result.width,
        result.height,
        0,
        status_row * cell_height,
        result.width,
        result.height,
        screenshot_color(7)
    );

    for (i32 y = 0; y < screen.height(); ++y) {
        for (i32 x = 0; x < screen.width(); ++x) {
            const ScreenCell& cell = screen.at(x, y);

            if (cell.width == 0) {
                continue;
            }

            paint_screenshot_glyph(
                pixels,
                result.width,
                result.height,
                face,
                cell.glyph,
                cell.style,
                x,
                y,
                cell.width,
                cell_width,
                cell_height,
                baseline
            );

            for (char32_t mark : cell.combining) {
                paint_screenshot_glyph(
                    pixels,
                    result.width,
                    result.height,
                    face,
                    mark,
                    cell.style,
                    x,
                    y,
                    cell.width,
                    cell_width,
                    cell_height,
                    baseline
                );
            }
        }
    }

    i32 status_column = 0;

    for (u32 byte = 0;
         byte < status.size() && status_column < screen.width();) {
        const Rune rune = decode_utf8(status, byte);
        const DisplayRune display = display_rune(rune.codepoint);

        if (status_column + display.width > screen.width()) {
            break;
        }

        paint_screenshot_glyph(
            pixels,
            result.width,
            result.height,
            face,
            display.glyph,
            Style{0, 7, AttrNone},
            status_column,
            status_row,
            display.width,
            cell_width,
            cell_height,
            baseline
        );
        status_column += display.width;
        byte += rune.bytes;
    }

    return encode_screenshot_png(pixels, result);
}

bool png_screenshot(
    const Screen& screen,
    std::string_view status,
    u32 font_pixels,
    PngScreenshot& result
) {
    result = PngScreenshot{};
    FontRasterizer font;

    if (!font.open_default(font_pixels)) {
        return false;
    }

    return render_png_screenshot(
        screen,
        status,
        font,
        result
    );
}
