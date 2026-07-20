#pragma once

#include "../board.hpp"
#include "../formats/format.hpp"
#include "../glyph_layer.hpp"
#include "../spatial/board_spatial.hpp"

#include <cstddef>
#include <cstdint>
#include <ostream>
#include <string>

namespace whiteboard::verification {

inline constexpr char kCanonicalSnapshotMagic[] =
    "WHITEBOARD-SNAPSHOT 2\n";

struct CanonicalSnapshotCursor {
    std::uint64_t card = 0;
    std::uint64_t edge = 0;
    std::uint64_t glyph = 0;

    friend bool operator==(
        const CanonicalSnapshotCursor&,
        const CanonicalSnapshotCursor&
    ) = default;
};

struct CanonicalSnapshotPage {
    CanonicalSnapshotCursor next{};
    bool done = false;
    std::string body;
};

enum class CanonicalSnapshotResult {
    Success,
    InvalidCursor,
    InvalidDocument,
    RecordTooLarge,
    OutputFailed,
};

// Produces byte-exact pages. Cursors are opaque continuation tokens that may
// resume within a large record. Deleted slots remain observable through META
// without appearing as records.
CanonicalSnapshotResult make_canonical_snapshot_page(
    const Board& board,
    const CardSpatial& spatial,
    const GlyphLayer& glyphs,
    const CardFormats& formats,
    CanonicalSnapshotCursor cursor,
    std::size_t maximum_body_bytes,
    CanonicalSnapshotPage& page
);

bool write_canonical_snapshot(
    std::ostream& output,
    const Board& board,
    const CardSpatial& spatial,
    const GlyphLayer& glyphs,
    const CardFormats& formats
);

} // namespace whiteboard::verification
