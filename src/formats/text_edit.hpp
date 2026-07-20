#pragma once

#include "format.hpp"

#include <string>
#include <string_view>

Extent measure_text_card(const CardData& data);
void begin_text_card(FormatSession& session, const CardData& data);
void rebuild_text_card(CardData& card_data);

i32 text_visual_rune_width(char32_t codepoint, i32 cell);

void draw_text_card(
    Screen& screen,
    const CardData& card_data,
    CardId id,
    i32 x,
    i32 y,
    const CardFormat& format,
    CardVisualState state,
    const FormatSession* active_session
);

void swap_text_layout_undo(
    TextCardData& data,
    TextSession* session,
    TextLayoutUndo& undo,
    bool soft_wrap
);

FormatAction replace_text_action(
    TextCardData& data,
    TextSession& session,
    TextRange range,
    std::string_view inserted,
    bool soft_wrap,
    std::string replaced
);

FormatAction replace_text_action(
    TextCardData& data,
    TextSession& session,
    TextRange range,
    std::string_view inserted,
    bool soft_wrap
);

void swap_text_undo(
    TextCardData& data,
    TextSession* session,
    TextUndo& undo,
    bool soft_wrap
);

void swap_text_style_undo(
    TextCardData& data,
    TextStyleUndo& undo
);

void swap_text_format_undo(
    CardData& card_data,
    FormatSession* format_session,
    FormatUndo& undo,
    bool soft_wrap,
    bool supports_style_undo
);

FormatAction resize_text_card(
    FormatContext& context,
    const InputEvent& event,
    bool soft_wrap
);

FormatAction handle_text_input(
    FormatContext& context,
    const InputEvent& event,
    bool soft_wrap
);

using TextSpecialInputFunction = FormatAction (*)(FormatContext&);

FormatAction handle_text_card_input(
    FormatContext& context,
    const InputEvent& event,
    bool soft_wrap,
    TextSpecialInputFunction control_b = nullptr
);
