#pragma once

#include "types.hpp"

#include <absl/container/inlined_vector.h>

#include <memory>
#include <string>
#include <string_view>
#include <utility>
#include <variant>
#include <vector>

enum class SaveFormat : u8 {
    PlainText = 0,
    Markdown = 1,
    TodoText = 2,
    Csv = 3,
    FolderTree = 4,
};

struct TextSpan {
    u32 row = 0;
    u32 begin_byte = 0;
    u32 end_byte = 0;
    Style style{};

    friend bool operator==(const TextSpan&, const TextSpan&) = default;
};

using RowTextSpans = absl::InlinedVector<TextSpan, 2>;

struct RowStyles {
    u32 row = 0;
    RowTextSpans spans;

    RowStyles() = default;

    explicit RowStyles(u32 value) : row(value) {}

    RowStyles(u32 value, TextSpan span)
        : row(value), spans{std::move(span)} {}

    friend bool operator==(const RowStyles&, const RowStyles&) = default;
};

using TextStyles = absl::InlinedVector<RowStyles, 1>;
using TextLines = absl::InlinedVector<std::string, 1>;

inline std::size_t text_style_span_count(
    const TextStyles& styles
) noexcept {
    std::size_t count = 0;

    for (const RowStyles& row : styles) {
        count += row.spans.size();
    }

    return count;
}

struct TextCardData {
    Extent layout{32, 12};
    LanguageId language = 0;
    TextLines lines{std::string{}};

    // 格式可以保存或重建的渲染資料。
    TextStyles styles;

    friend bool operator==(
        const TextCardData&,
        const TextCardData&
    ) = default;
};

struct TodoItem {
    std::string text;
    bool done = false;
    Style style{7, 0, AttrNone};

    TodoItem() = default;

    TodoItem(std::string value, bool completed)
        : text(std::move(value)),
          done(completed),
          style(completed
              ? Style{2, 0, AttrNone}
              : Style{7, 0, AttrNone}) {}

    friend bool operator==(const TodoItem&, const TodoItem&) = default;
};

using TodoItems = absl::InlinedVector<TodoItem, 1>;

struct TodoCardData {
    Extent layout{32, 12};
    TodoItems items{TodoItem{}};

    friend bool operator==(const TodoCardData&, const TodoCardData&) = default;
};

struct CsvCellStyle {
    u32 row = 0;
    u32 column = 0;
    Style style{};

    friend bool operator==(const CsvCellStyle&, const CsvCellStyle&) = default;
};

using CsvColumnWidths = absl::InlinedVector<i32, 4>;
using CsvCellStyles = absl::InlinedVector<CsvCellStyle, 1>;

struct CsvCardData {
    Extent layout{42, 12};
    std::vector<std::vector<std::string>> cells{
        std::vector<std::string>(3)
    };

    // 與欄數平行，由 csv.hpp 維持一致。
    CsvColumnWidths column_widths{12, 12, 12};
    CsvCellStyles styled_cells;

    friend bool operator==(const CsvCardData&, const CsvCardData&) = default;
};

enum class FolderEntryKind : u8 {
    Directory,
    Card,
};

struct FolderEntry {
    FolderEntryKind kind = FolderEntryKind::Card;
    u32 depth = 0;
    std::string name;
    CardId target = kNoCard;
    bool collapsed = false;

    friend bool operator==(const FolderEntry&, const FolderEntry&) = default;
};

struct FolderCardData {
    Extent layout{36, 14};
    std::string name;
    std::vector<FolderEntry> entries;

    friend bool operator==(
        const FolderCardData&,
        const FolderCardData&
    ) = default;
};

constexpr u32 kNoFolderEntry = ~u32{0};

using CardData = std::variant<
    TextCardData,
    TodoCardData,
    CsvCardData,
    FolderCardData
>;

struct Card {
    Pos pos;
    StaticFormatId static_format = 0;
    CardData data;

    Card() = default;

    Card(const Card&) = delete;
    Card& operator=(const Card&) = delete;

    Card(Card&&) noexcept = default;
    Card& operator=(Card&&) noexcept = default;
};

inline std::string_view card_name(const Card& card) {
    if (const auto* folder =
            std::get_if<FolderCardData>(&card.data)) {
        if (!folder->name.empty()) {
            return folder->name;
        }
    }

    return {};
}

enum class PortSide : u8 {
    Top,
    Right,
    Bottom,
    Left,
};

struct EdgeEnd {
    CardId card = kNoCard;
    PortSide side = PortSide::Right;
};

enum class RouteMode : u8 {
    Automatic,
    Manual,
};

enum class RouteState : u8 {
    Ready,
    Blocked,
};

using EdgePoints = absl::InlinedVector<Pos, 2>;

struct Edge {
    EdgeEnd source{};
    EdgeEnd target{};
    RouteMode mode = RouteMode::Automatic;
    RouteState state = RouteState::Ready;
    Rect route_bounds{};
    // Most normalized edges are a direct segment. Keep that geometry in the
    // edge slot and allocate only for paths that actually turn.
    EdgePoints points;
};
