#pragma once

#include "../board.hpp"
#include "../formats/format.hpp"
#include "../spatial/board_spatial.hpp"
#include "screenshot.hpp"

enum class BoardThumbnailResult : u8 {
    Success,
    Empty,
    Failed,
};

enum class BoardThumbnailLabel : u8 {
    Name,
    Format,
    CardId,
};

inline constexpr u32 kBoardThumbnailMinimumSide = 64;
inline constexpr u32 kBoardThumbnailMaximumSide = 4'096;

BoardThumbnailResult board_thumbnail_png(
    const Board& board,
    const CardSpatial& spatial,
    const CardFormats& formats,
    u32 max_side,
    BoardThumbnailLabel label,
    const Rect* viewport,
    PngScreenshot& result
);
