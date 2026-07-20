#pragma once

#include "../board.hpp"

#include <string>
#include <string_view>
#include <vector>

enum class FolderExportIssueKind : u8 {
    InvalidName,
    MissingCard,
    DuplicatePath,
    UnsupportedFormat,
};

struct FolderExportItem {
    std::string relative_path;
    CardId card = kNoCard;
    SaveFormat format = SaveFormat::PlainText;
};

struct FolderExportIssue {
    FolderExportIssueKind kind = FolderExportIssueKind::InvalidName;
    u32 entry = kNoFolderEntry;
    CardId card = kNoCard;
    std::string relative_path;
};

struct FolderExportPlan {
    std::vector<std::string> directories;
    std::vector<FolderExportItem> files;
    std::vector<FolderExportIssue> issues;

    bool valid() const noexcept {
        return issues.empty();
    }
};

enum class FolderExportError : u8 {
    None,
    InvalidPlan,
    RootExists,
    CreateDirectory,
    OpenFile,
    WriteFile,
};

struct FolderExportResult {
    FolderExportError error = FolderExportError::None;
    FolderExportIssueKind issue = FolderExportIssueKind::InvalidName;
    std::string path;
    CardId card = kNoCard;
    u32 files_written = 0;
    int system_error = 0;

    bool ok() const noexcept {
        return error == FolderExportError::None;
    }
};

FolderExportPlan build_folder_export_plan(
    const Board& board,
    const FolderCardData& data
);

FolderExportResult write_folder_export(
    const Board& board,
    const FolderCardData& data,
    std::string_view destination_parent
);
