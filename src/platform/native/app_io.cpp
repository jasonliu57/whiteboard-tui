#include "app_io.hpp"
#include "../../app.hpp"
#include "../../storage/native.hpp"

namespace whiteboard::native {
FolderExportResult export_folder(const App& app, CardId id, std::string_view parent) {
    return write_folder_export(app.board,
        std::get<FolderCardData>(app.board.get(id).data), parent);
}

bool save(App& app, const std::string& path) {
    if (!whiteboard::io::save_project(path, app.board, app.glyphs, &app.file_error))
        return false;
    return app.mark_saved(app.revision);
}

bool load(App& app, const std::string& path) {
    Board board;
    CardSpatial spatial;
    GlyphLayer glyphs;
    if (!whiteboard::io::load_project(path, board, spatial, glyphs,
                                     app.formats, &app.file_error)) return false;
    app.commit_loaded(std::move(board), std::move(spatial), std::move(glyphs));
    return true;
}
} // namespace whiteboard::native
