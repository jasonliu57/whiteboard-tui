#pragma once

#include "../../storage/folder_export.hpp"
#include <string>

struct App;

namespace whiteboard::native {
bool save(App& app, const std::string& path);
bool load(App& app, const std::string& path);
FolderExportResult export_folder(const App& app, CardId id, std::string_view parent);
} // namespace whiteboard::native
