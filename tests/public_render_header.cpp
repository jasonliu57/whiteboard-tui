#include "render/font_rasterizer.hpp"

#include <type_traits>

static_assert(!std::is_copy_constructible_v<FontRasterizer>);
