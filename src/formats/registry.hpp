#pragma once

#include "format.hpp"
#include "../generated/card_formats.hpp"
#include "../languages/ids.hpp"

inline constexpr StaticFormatId kPlainTextNoteStaticFormatId = 0;
inline constexpr StaticFormatId kMarkdownStaticFormatId = 1;
inline constexpr StaticFormatId kCodeStaticFormatId = 2;
inline constexpr StaticFormatId kTodoStaticFormatId = 3;
inline constexpr StaticFormatId kCsvStaticFormatId = 4;
inline constexpr StaticFormatId kFolderStaticFormatId = 5;
inline constexpr StaticFormatId kTextArtStaticFormatId = 6;
inline constexpr Extent kTextArtMinimumLayout{
    kCardFormatTextArt.minimum_width,
    kCardFormatTextArt.minimum_height,
};
inline constexpr Extent kTextArtMaximumLayout{
    kCardFormatTextArt.maximum_width,
    kCardFormatTextArt.maximum_height,
};

inline void apply_generated_card_format_contract(
    CardFormat& format,
    const GeneratedCardFormatContract& contract
) {
    format.minimum_layout = {contract.minimum_width, contract.minimum_height};
    format.maximum_layout = {contract.maximum_width, contract.maximum_height};
}

// Content exchange/export format is derived from the static card registry.
inline SaveFormat card_save_format(const Card& card) noexcept {
    switch (card.static_format) {
        case kPlainTextNoteStaticFormatId: return static_cast<SaveFormat>(kCardFormatNote.save_format);
        case kMarkdownStaticFormatId: return static_cast<SaveFormat>(kCardFormatMarkdown.save_format);
        case kCodeStaticFormatId: return static_cast<SaveFormat>(kCardFormatCode.save_format);
        case kTodoStaticFormatId: return static_cast<SaveFormat>(kCardFormatTodo.save_format);
        case kCsvStaticFormatId: return static_cast<SaveFormat>(kCardFormatCsv.save_format);
        case kFolderStaticFormatId: return static_cast<SaveFormat>(kCardFormatFolder.save_format);
        case kTextArtStaticFormatId: return static_cast<SaveFormat>(kCardFormatTextArt.save_format);
        default: return static_cast<SaveFormat>(255);
    }
}

enum class TextArtBuildResult : u8 {
    Success,
    Empty,
    TooLarge,
};

enum class TextArtGlyphResult : u8 {
    Success,
    UnsupportedGlyph,
    OutsideCoordinateRange,
};

CardFormat make_plain_text_note_format();
CardFormat make_markdown_format();
CardFormat make_code_format();
CardFormat make_todo_format();
CardFormat make_csv_format();
CardFormat make_folder_format();
CardFormat make_text_art_format();

Card make_plain_text_note(Pos pos, i32 width = 32, i32 height = 12);
Card make_markdown_card(Pos pos, i32 width = 40, i32 height = 14);
Card make_code_card(
    Pos pos,
    LanguageId language = kCppLanguageId,
    i32 width = 48,
    i32 height = 16
);
Card make_todo_card(Pos pos, i32 width = 32, i32 height = 12);
Card make_csv_card(Pos pos, i32 width = 42, i32 height = 12);
Card make_folder_card(Pos pos, i32 width = 36, i32 height = 14);
Card make_empty_text_art_card(Pos pos, i32 width, i32 height);

Rect text_art_frame(const GlyphLayer& glyphs, Rect selection);
TextArtBuildResult make_text_art_card(
    const GlyphLayer& glyphs,
    Rect selection,
    std::vector<GlyphCell>& selected,
    Card& result
);
TextArtGlyphResult make_text_art_glyphs(
    const Card& card,
    std::vector<GlyphCell>& result
);

CardFormats make_card_formats();

bool create_registered_card(
    const CardFormats& formats,
    StaticFormatId id,
    Pos position,
    Extent extent,
    Card& result
);

bool create_registered_card(
    const CardFormats& formats,
    std::string_view line,
    Card& result
);

enum class RegisteredCardBatchResult {
    Success,
    Empty,
    InvalidLine,
};

RegisteredCardBatchResult build_registered_card_batch(
    const CardFormats& formats,
    std::string_view text,
    std::vector<Card>& result,
    u32& invalid_line
);
