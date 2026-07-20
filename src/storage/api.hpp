#pragma once

#include "../types.hpp"
#include "limits.hpp"
#include "../board.hpp"
#include "../formats/format.hpp"
#include "../glyph_layer.hpp"
#include "../spatial/board_spatial.hpp"

#include <string>
#include <string_view>
#include <ostream>
#include <istream>

namespace whiteboard::io {

// Encodes the current native format without filesystem access.
bool encode_project(std::ostream& output, const Board& board,
                    const GlyphLayer& glyphs, std::string* error = nullptr);

// Validates into temporary state; all outputs remain intact on failure.
bool decode_project(std::istream& input, u64 size, Board& board,
                    CardSpatial& spatial, GlyphLayer& glyphs,
                    const CardFormats& formats, std::string* error = nullptr,
                    u64 allocation_budget = kMaximumProjectAllocationBytes);

bool read_card_content(
    std::string_view content,
    SaveFormat format,
    CardData& data
);

bool write_card_content(
    std::ostream& output,
    SaveFormat format,
    const CardData& data
);

// Stable text exchange form used by agent GET/replace and verification
// snapshots. Folder cards include their root and entry metadata.
bool write_exchange_card_content(
    std::ostream& output,
    const Card& card
);

} // namespace whiteboard::io
