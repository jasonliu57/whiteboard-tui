#pragma once

#include "format.hpp"

inline bool extent_in_format(
    Extent extent,
    const CardFormat& format
) noexcept {
    return
        extent.width >= format.minimum_layout.width &&
        extent.width <= format.maximum_layout.width &&
        extent.height >= format.minimum_layout.height &&
        extent.height <= format.maximum_layout.height;
}

inline bool card_data_matches(
    CardDataKind kind,
    const CardData& data
) noexcept {
    switch (kind) {
        case CardDataKind::Text:
            return std::holds_alternative<TextCardData>(data);
        case CardDataKind::Todo:
            return std::holds_alternative<TodoCardData>(data);
        case CardDataKind::Csv:
            return std::holds_alternative<CsvCardData>(data);
        case CardDataKind::Folder:
            return std::holds_alternative<FolderCardData>(data);
    }

    return false;
}
