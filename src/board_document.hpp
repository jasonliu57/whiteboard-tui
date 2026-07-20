#pragma once

#include "board.hpp"
#include "edge_route.hpp"
#include "glyph_layer.hpp"
#include "history.hpp"
#include "spatial/board_spatial.hpp"

#include <vector>

// Persistent model state owned exactly once by App. UI sessions, viewport,
// clipboard and framebuffer deliberately remain outside this document.
struct BoardDocument {
    Board board;
    GlyphLayer glyphs;
    CardSpatial spatial;
    EdgeSpatial edge_spatial;
    EdgeRouter edge_router;
    History history;
    std::vector<EdgeId> affected_edges;
    std::vector<u32> edge_marks;
    u32 edge_mark_generation = 0;
    bool untracked_dirty = false;
    u64 revision = 0;

    BoardDocument();

    BoardDocument(const BoardDocument&) = delete;
    BoardDocument& operator=(const BoardDocument&) = delete;

    bool dirty() const noexcept;
};
