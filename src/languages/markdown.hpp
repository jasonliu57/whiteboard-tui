#pragma once

#include "ids.hpp"

#include <string_view>

constexpr std::string_view kMarkdownBlockHighlights = R"query(
(atx_heading) @heading
(fenced_code_block_delimiter) @punctuation
(code_fence_content) @code
(language) @type
(block_quote_marker) @punctuation
(list_marker_star) @punctuation
(link_destination) @link
)query";

constexpr std::string_view kMarkdownInlineRegions = R"query(
(inline) @region
(pipe_table_cell) @region
)query";

constexpr std::string_view kMarkdownInlineHighlights = R"query(
(strong_emphasis) @strong
(emphasis) @emphasis
(code_span) @code
(link_text) @link
(link_destination) @link
(link_label) @link
)query";

static Style markdown_highlight_style(std::string_view capture) {
    if (capture == "heading") {
        return {6, 0, AttrBold};
    }

    if (capture == "strong") {
        return {7, 0, AttrBold};
    }

    if (capture == "emphasis") {
        return {3, 0, AttrUnderline};
    }

    if (capture == "code") {
        return {2, 0, AttrNone};
    }

    if (capture == "link") {
        return {4, 0, AttrUnderline};
    }

    if (capture == "type") {
        return {3, 0, AttrNone};
    }

    return {5, 0, AttrNone};
}
