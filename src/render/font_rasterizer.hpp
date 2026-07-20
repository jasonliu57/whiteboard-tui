#pragma once

#include "../types.hpp"

#include <ft2build.h>
#include FT_FREETYPE_H

class FontRasterizer {
public:
    FontRasterizer() = default;
    FontRasterizer(const FontRasterizer&) = delete;
    FontRasterizer& operator=(const FontRasterizer&) = delete;
    ~FontRasterizer();

    bool open_default(u32 pixel_height);
    bool open(const char* path, u32 pixel_height);

    FT_Face face() const noexcept {
        return face_;
    }

    i32 cell_width() const noexcept {
        return cell_width_;
    }

    i32 cell_height() const noexcept {
        return cell_height_;
    }

    i32 baseline() const noexcept {
        return baseline_;
    }

private:
    FT_Library library_ = nullptr;
    FT_Face face_ = nullptr;
    i32 cell_width_ = 0;
    i32 cell_height_ = 0;
    i32 baseline_ = 0;

    void reset() noexcept;
};
