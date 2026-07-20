#include "font_rasterizer.hpp"

#include <algorithm>
#include <array>
#include <cstdlib>

namespace {

#if defined(__APPLE__)
constexpr std::array kDefaultScreenshotFonts{
    "/Library/Fonts/SourceHanMono.ttc",
    "/Library/Fonts/SourceHanMono-Regular.otf",
    "/System/Library/Fonts/SFNSMono.ttf",
    "/System/Library/Fonts/Monaco.ttf",
    "/System/Library/Fonts/Supplemental/Andale Mono.ttf",
};
#else
constexpr std::array kDefaultScreenshotFonts{
    "/usr/share/fonts/adobe-source-han-mono/SourceHanMono.ttc",
    "/usr/share/fonts/opentype/source-han/SourceHanMono-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansMonoCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
};
#endif

} // namespace

FontRasterizer::~FontRasterizer() {
    reset();
}

bool FontRasterizer::open_default(u32 pixel_height) {
    const char* path = std::getenv("WHITEBOARD_TUI_SCREENSHOT_FONT");

    if (path != nullptr && *path != '\0') {
        return open(path, pixel_height);
    }

    for (const char* candidate : kDefaultScreenshotFonts) {
        if (open(candidate, pixel_height)) {
            return true;
        }
    }

    return false;
}

bool FontRasterizer::open(const char* path, u32 pixel_height) {
    reset();

    if (
        path == nullptr ||
        *path == '\0' ||
        FT_Init_FreeType(&library_) != 0 ||
        FT_New_Face(library_, path, 0, &face_) != 0 ||
        FT_Set_Pixel_Sizes(face_, 0, pixel_height) != 0 ||
        FT_Load_Char(face_, U'M', FT_LOAD_DEFAULT) != 0
    ) {
        reset();
        return false;
    }

    cell_width_ = std::max<i32>(
        1,
        static_cast<i32>(face_->glyph->advance.x >> 6)
    );
    cell_height_ = std::max<i32>(
        1,
        static_cast<i32>((face_->size->metrics.height + 63) >> 6)
    );
    baseline_ = static_cast<i32>(
        (face_->size->metrics.ascender + 63) >> 6
    );
    return true;
}

void FontRasterizer::reset() noexcept {
    if (face_ != nullptr) {
        FT_Done_Face(face_);
    }

    if (library_ != nullptr) {
        FT_Done_FreeType(library_);
    }

    face_ = nullptr;
    library_ = nullptr;
    cell_width_ = 0;
    cell_height_ = 0;
    baseline_ = 0;
}
