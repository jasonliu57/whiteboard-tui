#include "registry.hpp"
#include "text_edit.hpp"

static FormatAction bold_markdown_selection(
    FormatContext& context
) {
    TextCardData& data = std::get<TextCardData>(context.data);
    TextSession& session = std::get<TextSession>(context.session);
    const TextRange range = session.selection();

    if (range.begin == range.end) {
        return view_action();
    }

    std::string selected = extract_text(data.lines, range);
    std::string replacement;
    const std::size_t newline_count =
        range.end.row - range.begin.row;
    replacement.reserve(selected.size() + 4 + 4 * newline_count);
    replacement.append("**");

    for (std::size_t begin = 0;;) {
        const std::size_t end = selected.find('\n', begin);

        if (end == std::string::npos) {
            replacement.append(selected, begin);
            break;
        }

        replacement.append(selected, begin, end - begin);
        replacement.append("**\n**");
        begin = end + 1;
    }

    replacement.append("**");

    return replace_text_action(
        data,
        session,
        range,
        replacement,
        true,
        std::move(selected)
    );
}

static FormatAction input_markdown(
    FormatContext& context,
    const InputEvent& event
) {
    return handle_text_card_input(
        context,
        event,
        true,
        bold_markdown_selection
    );
}

static void swap_markdown_undo(
    CardData& card_data,
    FormatSession* format_session,
    FormatUndo& undo
) {
    swap_text_format_undo(
        card_data,
        format_session,
        undo,
        true,
        false
    );
}

CardFormat make_markdown_format() {
    CardFormat format;
    format.name = "markdown";
    format.data_kind = CardDataKind::Text;
    apply_generated_card_format_contract(format, kCardFormatMarkdown);
    format.border = Style{5, 0, AttrBold};
    format.body = Style{7, 0, AttrNone};
    format.title = Style{6, 0, AttrBold};
    format.active_border = Style{3, 0, AttrBold};
    format.soft_wrap = true;
    format.measure = measure_text_card;
    format.draw = draw_text_card;
    format.begin = begin_text_card;
    format.input = input_markdown;
    format.rebuild = rebuild_text_card;
    format.swap_undo = swap_markdown_undo;
    format.create_empty = make_markdown_card;
    return format;
}

Card make_markdown_card(
    Pos pos,
    i32 width,
    i32 height
) {
    TextCardData data;
    data.layout = {width, height};
    data.language = kMarkdownLanguageId;

    Card card;
    card.pos = pos;
    card.static_format = kMarkdownStaticFormatId;
    card.data = std::move(data);
    return card;
}
