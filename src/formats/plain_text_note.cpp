#include "internal.hpp"
#include "registry.hpp"
#include "text_edit.hpp"

FormatAction bold_plain_text_selection(
    FormatContext& context
) {
    TextCardData& data = std::get<TextCardData>(context.data);
    const TextSession& session =
        std::get<TextSession>(context.session);
    const TextRange range = session.selection();

    if (range.begin == range.end) {
        return view_action();
    }

    TextStyles previous = text_style_rows(
        data.styles,
        range.begin.row,
        range.end.row
    );
    TextStyleUndo undo{{
        .current_first_row = range.begin.row,
        .current_last_row = range.end.row,
        .replacement_first_row = range.begin.row,
        .replacement_last_row = range.end.row,
        .replacement = previous,
    }};
    TextStyles replacement = std::move(previous);
    const Style bold{7, 0, AttrBold};

    for (u32 row = range.begin.row; row <= range.end.row; ++row) {
        const u32 begin =
            row == range.begin.row ? range.begin.byte : 0;
        const u32 end =
            row == range.end.row
                ? range.end.byte
                : static_cast<u32>(data.lines[row].size());

        if (begin < end) {
            apply_text_span(
                replacement,
                {row, begin, end, bold}
            );
        }
    }

    replace_text_style_rows(
        data.styles,
        range.begin.row,
        range.end.row,
        replacement
    );

    return stored_action(FormatUndo{std::move(undo)});
}

static FormatAction input_plain_text_note(
    FormatContext& context,
    const InputEvent& event
) {
    return handle_text_card_input(
        context,
        event,
        false,
        bold_plain_text_selection
    );
}

static void swap_plain_text_note_undo(
    CardData& card_data,
    FormatSession* format_session,
    FormatUndo& undo
) {
    swap_text_format_undo(
        card_data,
        format_session,
        undo,
        false,
        true
    );
}

CardFormat make_plain_text_note_format() {
    CardFormat format;
    format.name = "note";
    format.data_kind = CardDataKind::Text;
    apply_generated_card_format_contract(format, kCardFormatNote);
    format.border = Style{7, 0, AttrBold};
    format.body = Style{7, 0, AttrNone};
    format.title = Style{6, 0, AttrBold};
    format.active_border = Style{3, 0, AttrBold};
    format.first_line_is_title = true;
    format.measure = measure_text_card;
    format.draw = draw_text_card;
    format.begin = begin_text_card;
    format.input = input_plain_text_note;
    format.rebuild = rebuild_text_card;
    format.swap_undo = swap_plain_text_note_undo;
    format.create_empty = make_plain_text_note;
    return format;
}

Card make_plain_text_note(
    Pos pos,
    i32 width,
    i32 height
) {
    TextCardData data;
    data.layout = {width, height};
    data.language = kPlainTextLanguageId;

    Card card;
    card.pos = pos;
    card.static_format = kPlainTextNoteStaticFormatId;
    card.data = std::move(data);
    return card;
}
