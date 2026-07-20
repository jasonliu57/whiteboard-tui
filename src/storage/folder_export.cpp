#include "folder_export.hpp"
#include "../formats/registry.hpp"

#include "api.hpp"

#include <absl/container/flat_hash_set.h>
#include <absl/container/inlined_vector.h>

#include <cerrno>
#include <fstream>
#include <utility>
#include <sys/stat.h>

namespace {

bool valid_folder_export_name(std::string_view name) {
    if (name.empty() || name == "." || name == "..") {
        return false;
    }

    for (char ch : name) {
        const u8 byte = static_cast<u8>(ch);

        if (byte < 0x20 || byte == 0x7F || ch == '/') {
            return false;
        }
    }

    return true;
}

void assign_folder_export_destination(
    std::string& path,
    std::string_view parent,
    std::string_view relative_path
) {
    if (parent.empty()) {
        path.assign(relative_path);
        return;
    }

    path.assign(parent);

    if (path.back() != '/') {
        path.push_back('/');
    }

    path.append(relative_path);
}

FolderExportResult folder_export_io_error(
    FolderExportError error,
    std::string path,
    u32 files_written
) {
    return {
        .error = error,
        .path = std::move(path),
        .files_written = files_written,
        .system_error = errno,
    };
}

} // namespace

FolderExportPlan build_folder_export_plan(
    const Board& board,
    const FolderCardData& data
) {
    FolderExportPlan plan;

    if (!valid_folder_export_name(data.name)) {
        plan.issues.push_back({
            .kind = FolderExportIssueKind::InvalidName,
            .entry = kNoFolderEntry,
            .card = kNoCard,
            .relative_path = data.name,
        });
        return plan;
    }

    absl::InlinedVector<std::size_t, 16> prefix_lengths{
        data.name.size()
    };
    std::string path = data.name;
    absl::flat_hash_set<std::string> used;
    used.reserve(data.entries.size() + 1);
    used.insert(data.name);
    plan.directories.push_back(data.name);

    for (u32 i = 0; i < data.entries.size(); ++i) {
        const FolderEntry& entry = data.entries[i];

        if (entry.depth >= prefix_lengths.size()) {
            plan.issues.push_back({
                .kind = FolderExportIssueKind::InvalidName,
                .entry = i,
                .card = entry.target,
                .relative_path = entry.name,
            });
            continue;
        }

        path.resize(prefix_lengths[entry.depth]);
        path.push_back('/');
        path.append(entry.name);

        if (!valid_folder_export_name(entry.name)) {
            plan.issues.push_back({
                .kind = FolderExportIssueKind::InvalidName,
                .entry = i,
                .card = entry.target,
                .relative_path = path,
            });
        } else if (!used.insert(path).second) {
            plan.issues.push_back({
                .kind = FolderExportIssueKind::DuplicatePath,
                .entry = i,
                .card = entry.target,
                .relative_path = path,
            });
        } else if (entry.kind == FolderEntryKind::Directory) {
            plan.directories.push_back(path);
        } else {
            const Card* target = board.find(entry.target);

            if (target == nullptr) {
                plan.issues.push_back({
                    .kind = FolderExportIssueKind::MissingCard,
                    .entry = i,
                    .card = entry.target,
                    .relative_path = path,
                });
            } else if (card_save_format(*target) == SaveFormat::FolderTree) {
                plan.issues.push_back({
                    .kind = FolderExportIssueKind::UnsupportedFormat,
                    .entry = i,
                    .card = entry.target,
                    .relative_path = path,
                });
            } else {
                plan.files.push_back({
                    .relative_path = path,
                    .card = entry.target,
                    .format = card_save_format(*target),
                });
            }
        }

        if (entry.kind == FolderEntryKind::Directory) {
            prefix_lengths.resize(entry.depth + 1);
            prefix_lengths.push_back(path.size());
        }
    }

    return plan;
}

FolderExportResult write_folder_export(
    const Board& board,
    const FolderCardData& data,
    std::string_view destination_parent
) {
    FolderExportPlan plan = build_folder_export_plan(board, data);

    if (!plan.valid()) {
        FolderExportIssue& issue = plan.issues.front();
        return {
            .error = FolderExportError::InvalidPlan,
            .issue = issue.kind,
            .path = std::move(issue.relative_path),
            .card = issue.card,
        };
    }

    std::string root;
    assign_folder_export_destination(
        root,
        destination_parent,
        plan.directories.front()
    );

    if (::mkdir(root.c_str(), 0777) != 0) {
        return folder_export_io_error(
            errno == EEXIST
                ? FolderExportError::RootExists
                : FolderExportError::CreateDirectory,
            std::move(root),
            0
        );
    }

    std::string path;

    for (u32 i = 1; i < plan.directories.size(); ++i) {
        assign_folder_export_destination(
            path,
            destination_parent,
            plan.directories[i]
        );

        if (::mkdir(path.c_str(), 0777) != 0) {
            return folder_export_io_error(
                FolderExportError::CreateDirectory,
                std::move(path),
                0
            );
        }
    }

    u32 files_written = 0;

    for (const FolderExportItem& item : plan.files) {
        assign_folder_export_destination(
            path,
            destination_parent,
            item.relative_path
        );
        std::ofstream output(path, std::ios::out | std::ios::trunc);

        if (!output) {
            return folder_export_io_error(
                FolderExportError::OpenFile,
                std::move(path),
                files_written
            );
        }

        const Card& card = board.get(item.card);

        if (!whiteboard::io::write_card_content(
                output,
                item.format,
                card.data
            )) {
            return folder_export_io_error(
                FolderExportError::WriteFile,
                std::move(path),
                files_written
            );
        }

        output.close();

        if (!output) {
            return folder_export_io_error(
                FolderExportError::WriteFile,
                std::move(path),
                files_written
            );
        }

        ++files_written;
    }

    return {
        .path = std::move(root),
        .files_written = files_written,
    };
}
