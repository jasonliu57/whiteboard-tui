#include "registry.hpp"
#include "text_edit.hpp"

static FormatAction input_code(
    FormatContext& context,
    const InputEvent& event
) {
    return handle_text_card_input(context, event, false);
}

static void swap_code_undo(
    CardData& card_data,
    FormatSession* format_session,
    FormatUndo& undo
) {
    swap_text_format_undo(
        card_data,
        format_session,
        undo,
        false,
        false
    );
}

CardFormat make_code_format() {
    CardFormat format;
    format.name = "code";
    format.data_kind = CardDataKind::Text;
    apply_generated_card_format_contract(format, kCardFormatCode);
    format.border = Style{4, 0, AttrBold};
    format.body = Style{7, 0, AttrNone};
    format.title = Style{4, 0, AttrBold};
    format.active_border = Style{3, 0, AttrBold};
    format.measure = measure_text_card;
    format.draw = draw_text_card;
    format.begin = begin_text_card;
    format.input = input_code;
    format.rebuild = rebuild_text_card;
    format.swap_undo = swap_code_undo;
    format.create_empty = [](Pos pos, i32 width, i32 height) {
        return make_code_card(pos, kCppLanguageId, width, height);
    };
    return format;
}

Card make_code_card(
    Pos pos,
    LanguageId language,
    i32 width,
    i32 height
) {
    TextCardData data;
    data.layout = {width, height};
    data.language = language;

    Card card;
    card.pos = pos;
    card.static_format = kCodeStaticFormatId;
    card.data = std::move(data);
    return card;
}
