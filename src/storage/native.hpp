#pragma once

#include "api.hpp"

namespace whiteboard::io {

// Publishes a complete standalone file. A false result may mean the new file
// was published but directory synchronization failed; error describes that case.
bool save_project(
    const std::string& main_file,
    const Board& board,
    const GlyphLayer& glyphs,
    std::string* error = nullptr
);

// Read-only. Decodes into temporary objects and leaves outputs intact on failure.
// Accepts the native format documented in docs/file-format.md.
bool load_project(
    const std::string& main_file,
    Board& board,
    CardSpatial& spatial,
    GlyphLayer& glyphs,
    const CardFormats& formats,
    std::string* error = nullptr
);


} // namespace whiteboard::io
