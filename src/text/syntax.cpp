#include "syntax.hpp"

#include "../languages/cpp.hpp"
#include "../languages/markdown.hpp"

#include <tree_sitter/tree-sitter-markdown-inline.h>
#include <tree_sitter/tree-sitter-markdown.h>

#include <algorithm>
#include <cstdlib>
#include <iterator>
#include <limits>
#include <string>
#include <utility>

using HighlightStyleFunction = Style (*)(std::string_view);
using SyntaxRanges = absl::InlinedVector<TSRange, 4>;
using SyntaxNodes = absl::InlinedVector<TSNode, 16>;

SyntaxLayer::SyntaxLayer(SyntaxLayer&& other) noexcept {
    move_from(other);
}

SyntaxLayer& SyntaxLayer::operator=(SyntaxLayer&& other) noexcept {
    if (this != &other) {
        reset();
        move_from(other);
    }

    return *this;
}

SyntaxLayer::~SyntaxLayer() {
    reset();
}

void SyntaxLayer::clear_tree() {
    if (tree != nullptr) {
        ts_tree_delete(tree);
    }
    tree = nullptr;

    for (InlineSyntaxTree& extra : extra_trees) {
        if (extra.tree != nullptr) {
            ts_tree_delete(extra.tree);
        }
    }
    extra_trees.clear();
}

void SyntaxLayer::reset() {
    if (cursor != nullptr) {
        ts_query_cursor_delete(cursor);
    }

    if (query != nullptr) {
        ts_query_delete(query);
    }

    if (regions != nullptr) {
        ts_query_delete(regions);
    }

    clear_tree();

    if (parser != nullptr) {
        ts_parser_delete(parser);
    }

    parser = nullptr;
    query = nullptr;
    regions = nullptr;
    cursor = nullptr;
}

void SyntaxLayer::move_from(SyntaxLayer& other) noexcept {
    parser = std::exchange(other.parser, nullptr);
    tree = std::exchange(other.tree, nullptr);
    query = std::exchange(other.query, nullptr);
    regions = std::exchange(other.regions, nullptr);
    cursor = std::exchange(other.cursor, nullptr);
    extra_trees = std::move(other.extra_trees);
    other.extra_trees.clear();
}

TextRange TextSession::selection() const {
    return ordered_range(selection_anchor, cursor);
}

static const char* read_text_input(
    void* payload,
    u32,
    TSPoint position,
    u32* bytes_read
) {
    const auto& lines =
        *static_cast<const TextLines*>(payload);

    if (position.row >= lines.size()) {
        *bytes_read = 0;
        return nullptr;
    }

    const std::string& line = lines[position.row];

    if (position.column < line.size()) {
        *bytes_read = static_cast<u32>(
            line.size() - position.column
        );
        return line.data() + position.column;
    }

    if (
        position.column == line.size() &&
        position.row + 1 < lines.size()
    ) {
        *bytes_read = 1;
        return "\n";
    }

    *bytes_read = 0;
    return nullptr;
}

static TSInput make_text_input(const TextCardData& data) {
    return {
        .payload = const_cast<TextLines*>(&data.lines),
        .read = read_text_input,
        .encoding = TSInputEncodingUTF8,
        .decode = nullptr,
    };
}

static bool open_syntax_layer(
    SyntaxLayer& layer,
    const TSLanguage* language,
    std::string_view query_source
) {
    layer.parser = ts_parser_new();

    if (
        layer.parser == nullptr ||
        !ts_parser_set_language(layer.parser, language)
    ) {
        layer.reset();
        return false;
    }

    u32 error_offset = 0;
    TSQueryError error_type = TSQueryErrorNone;
    layer.query = ts_query_new(
        language,
        query_source.data(),
        static_cast<u32>(query_source.size()),
        &error_offset,
        &error_type
    );
    layer.cursor = ts_query_cursor_new();

    if (layer.query == nullptr || layer.cursor == nullptr) {
        layer.reset();
        return false;
    }

    return true;
}

static bool open_syntax_regions(
    SyntaxLayer& layer,
    const TSLanguage* language,
    std::string_view query_source
) {
    u32 error_offset = 0;
    TSQueryError error_type = TSQueryErrorNone;
    layer.regions = ts_query_new(
        language,
        query_source.data(),
        static_cast<u32>(query_source.size()),
        &error_offset,
        &error_type
    );
    return layer.regions != nullptr;
}

static bool parse_syntax_layer(
    SyntaxLayer& layer,
    const TextCardData& data,
    SyntaxRanges& changed_ranges,
    bool& incremental
) {
    TSTree* previous = layer.tree;
    incremental = previous != nullptr;
    TSTree* next = ts_parser_parse(
        layer.parser,
        previous,
        make_text_input(data)
    );

    changed_ranges.clear();

    if (previous != nullptr && next != nullptr) {
        u32 count = 0;
        TSRange* ranges = ts_tree_get_changed_ranges(
            previous,
            next,
            &count
        );

        if (count != 0) {
            changed_ranges.assign(ranges, ranges + count);
        }
        std::free(ranges);
    }

    if (previous != nullptr) {
        ts_tree_delete(previous);
    }

    layer.tree = next;
    return next != nullptr;
}

static void append_inline_range(
    SyntaxRanges& ranges,
    TSPoint start_point,
    u32 start_byte,
    TSPoint end_point,
    u32 end_byte
) {
    ranges.push_back({
        start_point,
        end_point,
        start_byte,
        end_byte
    });
}

static void collect_inline_ranges(
    TSNode node,
    SyntaxRanges& ranges
) {
    TSPoint start_point = ts_node_start_point(node);
    u32 start_byte = ts_node_start_byte(node);
    const u32 child_count = ts_node_child_count(node);

    for (u32 i = 1; i < child_count; ++i) {
        const TSNode child = ts_node_child(node, i);

        if (!ts_node_is_named(child)) {
            continue;
        }

        append_inline_range(
            ranges,
            start_point,
            start_byte,
            ts_node_start_point(child),
            ts_node_start_byte(child)
        );
        start_point = ts_node_end_point(child);
        start_byte = ts_node_end_byte(child);
    }

    append_inline_range(
        ranges,
        start_point,
        start_byte,
        ts_node_end_point(node),
        ts_node_end_byte(node)
    );
}

static void append_syntax_span(
    TextStyles& spans,
    u32 row,
    u32 begin_byte,
    u32 end_byte,
    Style style
) {
    if (begin_byte < end_byte) {
        const TextSpan span{row, begin_byte, end_byte, style};

        if (!spans.empty() && spans.back().row == row) {
            spans.back().spans.push_back(span);
        } else {
            spans.emplace_back(row, span);
        }
    }
}

static void append_node_spans(
    const TextCardData& data,
    TSNode node,
    Style style,
    TextStyles& spans,
    u32 first_row,
    u32 end_row
) {
    const TSPoint start = ts_node_start_point(node);
    const TSPoint end = ts_node_end_point(node);

    if (start.row >= end_row || end.row < first_row) {
        return;
    }

    const u32 first = std::max(start.row, first_row);
    const u32 last = std::min(end.row, end_row - 1);

    for (u32 row = first; row <= last; ++row) {
        const u32 begin_byte = row == start.row ? start.column : 0;
        const u32 end_byte = row == end.row
            ? end.column
            : static_cast<u32>(data.lines[row].size());
        append_syntax_span(
            spans,
            row,
            begin_byte,
            end_byte,
            style
        );
    }
}

static void append_query_styles(
    const TextCardData& data,
    SyntaxLayer& layer,
    TSTree* tree,
    HighlightStyleFunction highlight_style,
    TextStyles& styles,
    u32 first_row,
    u32 end_row
) {
    ts_query_cursor_set_point_range(
        layer.cursor,
        {first_row, 0},
        {end_row, 0}
    );
    ts_query_cursor_exec(
        layer.cursor,
        layer.query,
        ts_tree_root_node(tree)
    );

    TSQueryMatch match{};
    u32 capture_index = 0;

    while (
        ts_query_cursor_next_capture(
            layer.cursor,
            &match,
            &capture_index
        )
    ) {
        const TSQueryCapture capture = match.captures[capture_index];
        u32 name_size = 0;
        const char* name = ts_query_capture_name_for_id(
            layer.query,
            capture.index,
            &name_size
        );
        const std::string_view capture_name{name, name_size};

        append_node_spans(
            data,
            capture.node,
            highlight_style(capture_name),
            styles,
            first_row,
            end_row
        );
    }
}

static void collect_inline_query_nodes(
    SyntaxLayer& layer,
    u32 first_row,
    u32 end_row,
    SyntaxNodes& nodes
) {
    if (layer.regions == nullptr) {
        return;
    }

    ts_query_cursor_set_point_range(
        layer.cursor,
        {first_row, 0},
        {end_row, 0}
    );
    ts_query_cursor_exec(
        layer.cursor,
        layer.regions,
        ts_tree_root_node(layer.tree)
    );

    TSQueryMatch match{};
    u32 capture_index = 0;

    while (
        ts_query_cursor_next_capture(
            layer.cursor,
            &match,
            &capture_index
        )
    ) {
        nodes.push_back(match.captures[capture_index].node);
    }
}

static TSRange node_range(TSNode node) {
    return {
        ts_node_start_point(node),
        ts_node_end_point(node),
        ts_node_start_byte(node),
        ts_node_end_byte(node),
    };
}

static bool same_syntax_range(TSRange first, TSRange second) {
    return
        first.start_byte == second.start_byte &&
        first.end_byte == second.end_byte &&
        first.start_point.row == second.start_point.row &&
        first.start_point.column == second.start_point.column &&
        first.end_point.row == second.end_point.row &&
        first.end_point.column == second.end_point.column;
}

static bool syntax_range_before(TSRange first, TSRange second) {
    return
        first.start_byte < second.start_byte ||
        (first.start_byte == second.start_byte &&
         first.end_byte < second.end_byte);
}

static u32 syntax_range_last_row(TSRange range) {
    return
        range.end_point.column == 0 &&
        range.end_point.row > range.start_point.row
            ? range.end_point.row - 1
            : range.end_point.row;
}

struct SyntaxRows {
    u32 first = 0;
    u32 last = 0;
};

static void include_syntax_range(
    SyntaxRows& rows,
    TSRange range
) {
    rows.first = std::min(rows.first, range.start_point.row);
    rows.last = std::max(rows.last, syntax_range_last_row(range));
}

static void replace_syntax_rows(
    TextCardData& data,
    u32 first_row,
    u32 last_row,
    TextStyles& replacement
) {
    canonicalize_text_styles(replacement, data.lines);

    replace_text_style_rows(
        data.styles,
        first_row,
        last_row,
        replacement
    );
}

static TSTree* parse_inline_syntax(
    SyntaxLayer& layer,
    const TextCardData& data,
    TSNode node
) {
    SyntaxRanges ranges;
    collect_inline_ranges(node, ranges);

    if (!ts_parser_set_included_ranges(
            layer.parser,
            ranges.data(),
            static_cast<u32>(ranges.size())
        )) {
        return nullptr;
    }

    return ts_parser_parse(
        layer.parser,
        nullptr,
        make_text_input(data)
    );
}

static SyntaxRows changed_syntax_rows(
    const TextCardData& data,
    const TextEdit* edit,
    const SyntaxRanges& changed_ranges
) {
    SyntaxRows rows = edit == nullptr
        ? SyntaxRows{
            0,
            static_cast<u32>(data.lines.size() - 1)
        }
        : SyntaxRows{
            edit->old_range.begin.row,
            std::max(
                edit->old_range.begin.row,
                edit->new_end.row
            )
        };

    for (TSRange range : changed_ranges) {
        include_syntax_range(rows, range);
    }

    const u32 last = static_cast<u32>(data.lines.size() - 1);
    rows.first = std::min(rows.first, last);
    rows.last = std::min(rows.last, last);
    return rows;
}

static void materialize_markdown_styles(
    TextSession& session,
    TextCardData& data,
    bool incremental,
    SyntaxRows rows
) {
    TextStyles replacement;
    const u32 first = incremental ? rows.first : 0;
    const u32 last = incremental
        ? rows.last
        : static_cast<u32>(data.lines.size() - 1);
    const u32 end = last + 1;

    append_query_styles(
        data,
        session.primary_syntax,
        session.primary_syntax.tree,
        markdown_highlight_style,
        replacement,
        first,
        end
    );

    const std::vector<InlineSyntaxTree>& inline_trees =
        session.inline_syntax.extra_trees;
    std::size_t inline_index = 0;

    if (incremental) {
        inline_index = static_cast<std::size_t>(std::lower_bound(
            inline_trees.begin(),
            inline_trees.end(),
            first,
            [](const InlineSyntaxTree& tree, u32 row) {
                return syntax_range_last_row(tree.range) < row;
            }
        ) - inline_trees.begin());
    }

    for (; inline_index < inline_trees.size(); ++inline_index) {
        const InlineSyntaxTree& inline_tree =
            inline_trees[inline_index];

        if (incremental && inline_tree.range.start_point.row > last) {
            break;
        }

        if (inline_tree.tree == nullptr) {
            continue;
        }

        append_query_styles(
            data,
            session.inline_syntax,
            inline_tree.tree,
            markdown_highlight_style,
            replacement,
            first,
            end
        );
    }

    if (incremental) {
        replace_syntax_rows(data, first, last, replacement);
    } else {
        data.styles = std::move(replacement);
        canonicalize_text_styles(data);
    }
}

static SyntaxRows parse_markdown_syntax(
    TextSession& session,
    TextCardData& data,
    const TextEdit* edit,
    TextStyles* previous_styles
) {
    SyntaxRanges changed_ranges;
    bool incremental = false;

    if (!parse_syntax_layer(
            session.primary_syntax,
            data,
            changed_ranges,
            incremental
        )) {
        const SyntaxRows rows{
            0,
            static_cast<u32>(data.lines.size() - 1)
        };

        if (previous_styles != nullptr) {
            *previous_styles = data.styles;
        }

        session.inline_syntax.clear_tree();
        data.styles.clear();
        return rows;
    }

    SyntaxRows rows = changed_syntax_rows(
        data,
        edit,
        changed_ranges
    );
    SyntaxNodes inline_nodes;
    collect_inline_query_nodes(
        session.primary_syntax,
        incremental ? rows.first : 0,
        incremental
            ? rows.last + 1
            : static_cast<u32>(data.lines.size()),
        inline_nodes
    );

    for (TSNode node : inline_nodes) {
        include_syntax_range(rows, node_range(node));
    }

    std::vector<InlineSyntaxTree>& inline_trees =
        session.inline_syntax.extra_trees;
    const std::size_t first_tree = static_cast<std::size_t>(
        std::lower_bound(
            inline_trees.begin(),
            inline_trees.end(),
            rows.first,
            [](const InlineSyntaxTree& tree, u32 row) {
                return syntax_range_last_row(tree.range) < row;
            }
        ) - inline_trees.begin()
    );
    std::size_t last_tree = first_tree;

    while (
        last_tree < inline_trees.size() &&
        inline_trees[last_tree].range.start_point.row <= rows.last
    ) {
        ++last_tree;
    }

    absl::InlinedVector<InlineSyntaxTree, 4> previous(
        inline_trees.begin() + first_tree,
        inline_trees.begin() + last_tree
    );
    inline_trees.erase(
        inline_trees.begin() + first_tree,
        inline_trees.begin() + last_tree
    );
    absl::InlinedVector<InlineSyntaxTree, 4> replacement;
    replacement.reserve(inline_nodes.size());
    std::size_t previous_index = 0;

    for (TSNode node : inline_nodes) {
        const TSRange range = node_range(node);

        while (
            previous_index < previous.size() &&
            syntax_range_before(
                previous[previous_index].range,
                range
            )
        ) {
            if (previous[previous_index].tree != nullptr) {
                ts_tree_delete(previous[previous_index].tree);
            }
            ++previous_index;
        }

        if (
            previous_index < previous.size() &&
            previous[previous_index].tree != nullptr &&
            same_syntax_range(
                previous[previous_index].range,
                range
            )
        ) {
            replacement.push_back(previous[previous_index]);
            previous[previous_index].tree = nullptr;
            ++previous_index;
            continue;
        }

        TSTree* tree = session.inline_syntax.parser == nullptr
            ? nullptr
            : parse_inline_syntax(
                session.inline_syntax,
                data,
                node
            );
        replacement.push_back({range, tree});
    }

    while (previous_index < previous.size()) {
        if (previous[previous_index].tree != nullptr) {
            ts_tree_delete(previous[previous_index].tree);
        }
        ++previous_index;
    }

    inline_trees.insert(
        inline_trees.begin() + first_tree,
        std::make_move_iterator(replacement.begin()),
        std::make_move_iterator(replacement.end())
    );

    rows.last = std::min(
        rows.last,
        static_cast<u32>(data.lines.size() - 1)
    );

    if (previous_styles != nullptr) {
        *previous_styles = text_style_rows(
            data.styles,
            rows.first,
            rows.last
        );
    }

    materialize_markdown_styles(
        session,
        data,
        incremental,
        rows
    );
    return rows;
}

static SyntaxRows parse_cpp_syntax(
    TextSession& session,
    TextCardData& data,
    const TextEdit* edit,
    TextStyles* previous_styles
) {
    SyntaxRanges changed_ranges;
    bool incremental = false;

    if (!parse_syntax_layer(
            session.primary_syntax,
            data,
            changed_ranges,
            incremental
        )) {
        const SyntaxRows rows{
            0,
            static_cast<u32>(data.lines.size() - 1)
        };

        if (previous_styles != nullptr) {
            *previous_styles = data.styles;
        }

        data.styles.clear();
        return rows;
    }

    const SyntaxRows rows = changed_syntax_rows(
        data,
        edit,
        changed_ranges
    );
    const u32 first = incremental ? rows.first : 0;
    const u32 last = incremental
        ? rows.last
        : static_cast<u32>(data.lines.size() - 1);

    if (previous_styles != nullptr) {
        *previous_styles = text_style_rows(
            data.styles,
            first,
            last
        );
    }

    TextStyles replacement;
    append_query_styles(
        data,
        session.primary_syntax,
        session.primary_syntax.tree,
        cpp_highlight_style,
        replacement,
        first,
        last + 1
    );

    if (incremental) {
        replace_syntax_rows(data, first, last, replacement);
    } else {
        data.styles = std::move(replacement);
        canonicalize_text_styles(data);
    }

    return {first, last};
}

static SyntaxRows parse_text_syntax(
    TextSession& session,
    TextCardData& data,
    const TextEdit* edit = nullptr,
    TextStyles* previous_styles = nullptr
) {
    if (session.language == kMarkdownLanguageId) {
        return parse_markdown_syntax(
            session,
            data,
            edit,
            previous_styles
        );
    } else if (session.language == kCppLanguageId) {
        return parse_cpp_syntax(
            session,
            data,
            edit,
            previous_styles
        );
    }

    return edit == nullptr
        ? SyntaxRows{
            0,
            static_cast<u32>(data.lines.size() - 1)
        }
        : SyntaxRows{
            edit->old_range.begin.row,
            std::max(edit->old_range.begin.row, edit->new_end.row)
        };
}

void begin_text_syntax(
    TextSession& session,
    TextCardData& data
) {
    session.language = data.language;
    session.byte_index.rebuild(data.lines);

    if (data.language == kMarkdownLanguageId) {
        if (!open_syntax_layer(
            session.primary_syntax,
            tree_sitter_markdown(),
            kMarkdownBlockHighlights
        )) {
            return;
        }

        open_syntax_regions(
            session.primary_syntax,
            tree_sitter_markdown(),
            kMarkdownInlineRegions
        );

        open_syntax_layer(
            session.inline_syntax,
            tree_sitter_markdown_inline(),
            kMarkdownInlineHighlights
        );
    } else if (data.language == kCppLanguageId) {
        if (!open_syntax_layer(
                session.primary_syntax,
                tree_sitter_cpp(),
                kCppHighlights
            )) {
            return;
        }
    } else {
        return;
    }

    parse_text_syntax(session, data);
}

static void edit_text_syntax(
    TextSession& session,
    const TextEdit& change
) {
    if (session.primary_syntax.tree == nullptr) {
        return;
    }

    const TSInputEdit edit{
        .start_byte = change.start_byte,
        .old_end_byte = change.old_end_byte,
        .new_end_byte = change.new_end_byte,
        .start_point = {
            change.old_range.begin.row,
            change.old_range.begin.byte
        },
        .old_end_point = {
            change.old_range.end.row,
            change.old_range.end.byte
        },
        .new_end_point = {change.new_end.row, change.new_end.byte},
    };

    ts_tree_edit(session.primary_syntax.tree, &edit);

    std::size_t output = 0;

    for (InlineSyntaxTree inline_tree :
         session.inline_syntax.extra_trees) {
        if (inline_tree.tree != nullptr) {
            ts_tree_edit(inline_tree.tree, &edit);
        }

        if (inline_tree.range.end_byte <= change.start_byte) {
            session.inline_syntax.extra_trees[output++] = inline_tree;
            continue;
        }

        if (inline_tree.range.start_byte >= change.old_end_byte) {
            const TextPos start = map_text_position_after_edit(
                change,
                {
                    inline_tree.range.start_point.row,
                    inline_tree.range.start_point.column
                }
            );
            const TextPos end = map_text_position_after_edit(
                change,
                {
                    inline_tree.range.end_point.row,
                    inline_tree.range.end_point.column
                }
            );

            if (change.new_end_byte >= change.old_end_byte) {
                const u32 delta =
                    change.new_end_byte - change.old_end_byte;
                inline_tree.range.start_byte += delta;
                inline_tree.range.end_byte += delta;
            } else {
                const u32 delta =
                    change.old_end_byte - change.new_end_byte;
                inline_tree.range.start_byte -= delta;
                inline_tree.range.end_byte -= delta;
            }

            inline_tree.range.start_point = {start.row, start.byte};
            inline_tree.range.end_point = {end.row, end.byte};
            session.inline_syntax.extra_trees[output++] = inline_tree;
            continue;
        }

        if (inline_tree.tree != nullptr) {
            ts_tree_delete(inline_tree.tree);
        }
    }

    session.inline_syntax.extra_trees.resize(output);
}

TextEdit replace_text_content(
    TextCardData& data,
    TextSession* session,
    TextRange range,
    std::string_view inserted,
    bool styles_follow_old_text,
    TextStyleChange* style_change
) {
    PreparedTextEdit prepared = prepare_text_edit(
        data.lines,
        range,
        inserted,
        session == nullptr ? nullptr : &session->byte_index
    );
    const TextEdit edit = prepared.edit;
    TextStyles old_edit_styles;

    if (style_change != nullptr) {
        old_edit_styles = text_style_rows(
            data.styles,
            range.begin.row,
            range.end.row
        );
    }

    if (session != nullptr) {
        edit_text_syntax(*session, edit);
    }

    if (styles_follow_old_text) {
        edit_text_styles(data.styles, edit);
    }

    apply_text_edit(data.lines, std::move(prepared));

    if (session != nullptr) {
        session->byte_index.after_edit(data.lines, edit);
    }

    SyntaxRows rows{
        range.begin.row,
        std::max(range.begin.row, edit.new_end.row)
    };
    TextStyles mapped_previous;

    if (
        session != nullptr &&
        session->primary_syntax.parser != nullptr
    ) {
        rows = parse_text_syntax(
            *session,
            data,
            &edit,
            style_change == nullptr ? nullptr : &mapped_previous
        );
    } else if (style_change != nullptr) {
        mapped_previous = text_style_rows(
            data.styles,
            rows.first,
            rows.last
        );
    }

    if (style_change != nullptr) {
        TextEdit inverse;
        inverse.old_range = {range.begin, edit.new_end};
        inverse.new_end = range.end;
        edit_text_styles(mapped_previous, inverse);

        for (const RowStyles& row : old_edit_styles) {
            for (const TextSpan& span : row.spans) {
                apply_text_span(mapped_previous, span);
            }
        }

        u32 replacement_first = range.begin.row;
        u32 replacement_last = range.end.row;

        if (rows.first < range.begin.row) {
            replacement_first = rows.first;
        }

        if (rows.last >= edit.new_end.row) {
            replacement_last = std::max(
                replacement_last,
                range.end.row + rows.last - edit.new_end.row
            );
        }

        *style_change = {
            .current_first_row = rows.first,
            .current_last_row = rows.last,
            .replacement_first_row = replacement_first,
            .replacement_last_row = replacement_last,
            .replacement = std::move(mapped_previous),
        };
    }

    return edit;
}
