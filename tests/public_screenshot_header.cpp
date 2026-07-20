#include "render/screenshot.hpp"

#include <type_traits>

static_assert(std::is_default_constructible_v<PngScreenshot>);
