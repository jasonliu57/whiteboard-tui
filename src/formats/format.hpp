#pragma once

#include "../glyph_layer.hpp"
#include "../model.hpp"
#include "../text/syntax.hpp"

#include <algorithm>
#include <array>
#include <cstddef>
#include <string>
#include <string_view>
#include <utility>
#include <variant>
#include <vector>

class Screen;

struct TodoSession {
    u32 selected_item = 0;
    u32 scroll_item = 0;
};

struct CsvSession {
    u32 row = 0;
    u32 column = 0;
    u32 row_scroll = 0;
    u32 column_scroll = 0;
};

struct FolderSession {
    u32 selected_entry = kNoFolderEntry;
    u32 scroll_row = 0;
};

using FormatSession = std::variant<
    std::monostate,
    TextSession,
    TodoSession,
    CsvSession,
    FolderSession
>;

struct CardSession {
    CardId active = kNoCard;
    FormatSession state;

    void end() {
        active = kNoCard;
        state = std::monostate{};
    }
};

struct CardClipboard {
    CardId source = kNoCard;
    std::string name;
    StaticFormatId static_format = 0;
    CardData data;
};

using Clipboard = std::variant<
    std::monostate,
    std::string,
    CardClipboard,
    GlyphClipboard
>;

struct TextUndo {
    TextRange range{};
    std::string text;
    TextStyleChange styles;
};

struct TextLayoutUndo {
    Extent layout{};
};

struct TextStyleUndo {
    TextStyleChange styles;
};

struct TodoLayoutUndo {
    Extent layout{};
};

struct TodoToggleUndo {
    u32 index = 0;
    bool done = false;
    Style style{};
};

struct TodoTextUndo {
    u32 index = 0;
    u32 begin_byte = 0;
    u32 end_byte = 0;
    std::string text;
};

struct TodoItemUndo {
    u32 index = 0;
    TodoItem item;
    bool item_present = false;
    u32 current_selection = 0;
    u32 replacement_selection = 0;
};

struct TodoReplaceItemUndo {
    u32 index = 0;
    TodoItem item;
};

struct TodoStyleUndo {
    u32 index = 0;
    Style style{};
};

struct CsvLayoutUndo {
    Extent layout{};
};

struct CsvTextUndo {
    u32 row = 0;
    u32 column = 0;
    u32 begin_byte = 0;
    u32 end_byte = 0;
    std::string text;
};

struct CsvStyleUndo {
    u32 row = 0;
    u32 column = 0;
    bool style_present = false;
    Style style{};
};

struct CsvRowUndo {
    u32 row = 0;
    bool row_present = false;
    std::vector<std::string> cells;
    CsvCellStyles styles;
    u32 current_row = 0;
    u32 replacement_row = 0;
    u32 current_column = 0;
    u32 replacement_column = 0;
};

struct CsvReplaceRowUndo {
    u32 row = 0;
    std::vector<std::string> cells;
    CsvCellStyles styles;
};

struct CsvWidthsUndo {
    CsvColumnWidths widths;
};

struct FolderLayoutUndo {
    Extent layout{};
};

struct FolderRenameUndo {
    u32 entry = kNoFolderEntry;
    u32 begin_byte = 0;
    u32 end_byte = 0;
    std::string text;
};

struct FolderCollapseUndo {
    u32 entry = kNoFolderEntry;
    bool collapsed = false;
};

struct FolderEntriesUndo {
    u32 position = 0;
    u32 count = 0;
    bool entries_present = false;
    std::vector<FolderEntry> entries;
    u32 current_selection = kNoFolderEntry;
    u32 replacement_selection = kNoFolderEntry;
};

struct FolderIndentUndo {
    u32 position = 0;
    u32 count = 0;
    u32 entry = kNoFolderEntry;
    bool collapsed = false;
    i32 depth_delta = 0;
};

struct FolderOutdentUndo {
    u32 position = 0;
    u32 count = 0;
    u32 move_end = 0;
    bool outdented = false;
    u32 current_selection = kNoFolderEntry;
    u32 replacement_selection = kNoFolderEntry;
};

using FormatUndo = std::variant<
    std::monostate,
    TextUndo,
    TextLayoutUndo,
    TextStyleUndo,
    TodoLayoutUndo,
    TodoToggleUndo,
    TodoTextUndo,
    TodoItemUndo,
    TodoReplaceItemUndo,
    TodoStyleUndo,
    CsvLayoutUndo,
    CsvTextUndo,
    CsvStyleUndo,
    CsvRowUndo,
    CsvReplaceRowUndo,
    CsvWidthsUndo,
    FolderLayoutUndo,
    FolderRenameUndo,
    FolderCollapseUndo,
    FolderEntriesUndo,
    FolderIndentUndo,
    FolderOutdentUndo
>;

enum class FormatMutation : u8 {
    None,
    View,
    Stored,
};

struct FormatAction {
    bool handled = false;
    FormatMutation mutation = FormatMutation::None;
    FormatUndo undo;
    bool layout_changed = false;
    bool focus_requested = false;
    CardId focus_card = kNoCard;
};

inline FormatAction view_action() {
    return {
        .handled = true,
        .mutation = FormatMutation::View,
        .undo = std::monostate{},
    };
}

inline FormatAction stored_action(FormatUndo&& undo) {
    return {
        .handled = true,
        .mutation = FormatMutation::Stored,
        .undo = std::move(undo),
    };
}

inline FormatAction stored_layout_action(FormatUndo&& undo) {
    FormatAction action = stored_action(std::move(undo));
    action.layout_changed = true;
    return action;
}

struct FormatContext {
    CardData& data;
    FormatSession& session;
    Clipboard& clipboard;
    Extent minimum_layout;
    Extent maximum_layout;
};

inline bool step_layout(
    const InputEvent& event,
    Extent current,
    Extent minimum,
    Extent maximum,
    Extent& next
) {
    if (!event.ctrl) {
        return false;
    }

    next = current;

    switch (event.key) {
        case Key::Left:  --next.width; break;
        case Key::Right: ++next.width; break;
        case Key::Up:    --next.height; break;
        case Key::Down:  ++next.height; break;
        default: return false;
    }

    next.width = std::clamp(
        next.width,
        minimum.width,
        maximum.width
    );
    next.height = std::clamp(
        next.height,
        minimum.height,
        maximum.height
    );
    return true;
}

enum class CardDataKind : u8 {
    Text,
    Todo,
    Csv,
    Folder,
};

struct CardFormat;

enum class CardVisualState : u8 {
    Normal,
    Hover,
    Selected,
    Editing,
};

using CardMeasureFunction = Extent (*)(const CardData&);

using CardDrawFunction = void (*)(
    Screen&,
    const CardData&,
    CardId,
    i32,
    i32,
    const CardFormat&,
    CardVisualState,
    const FormatSession*
);

using CardBeginFunction = void (*)(
    FormatSession&,
    const CardData&
);

using CardInputFunction = FormatAction (*)(
    FormatContext&,
    const InputEvent&
);

using CardRebuildFunction = void (*)(CardData&);

using CardUndoFunction = void (*)(
    CardData&,
    FormatSession*,
    FormatUndo&
);

using CardCreateFunction = Card (*)(Pos, i32, i32);

struct CardFormat {
    std::string_view name;
    CardDataKind data_kind = CardDataKind::Text;
    Extent minimum_layout{1, 1};
    Extent maximum_layout{1, 1};

    Style border{};
    Style body{};
    Style title{};
    Style active_border{};

    char32_t horizontal = U'─';
    char32_t vertical = U'│';
    char32_t top_left = U'┌';
    char32_t top_right = U'┐';
    char32_t bottom_left = U'└';
    char32_t bottom_right = U'┘';

    bool first_line_is_title = false;
    bool soft_wrap = false;
    bool borderless = false;

    CardMeasureFunction measure = nullptr;
    CardDrawFunction draw = nullptr;
    CardBeginFunction begin = nullptr;
    CardInputFunction input = nullptr;
    CardRebuildFunction rebuild = nullptr;
    CardUndoFunction swap_undo = nullptr;
    CardCreateFunction create_empty = nullptr;
};

constexpr std::size_t kCardFormatCount = 7;
using CardFormats = std::array<CardFormat, kCardFormatCount>;
