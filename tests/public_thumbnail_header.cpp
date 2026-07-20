#include "render/thumbnail.hpp"

static_assert(
    static_cast<u8>(BoardThumbnailResult::Success) == 0
);
static_assert(kBoardThumbnailMinimumSide == 64);
static_assert(kBoardThumbnailMaximumSide == 4'096);
