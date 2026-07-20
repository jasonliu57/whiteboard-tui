#pragma once

#include "../model.hpp"
#include "buffer.hpp"
#include "style.hpp"

#include <tree_sitter/api.h>

#include <string_view>
#include <vector>

struct InlineSyntaxTree {
    TSRange range{};
    TSTree* tree = nullptr;
};

struct SyntaxLayer {
    TSParser* parser = nullptr;
    TSTree* tree = nullptr;
    TSQuery* query = nullptr;
    TSQuery* regions = nullptr;
    TSQueryCursor* cursor = nullptr;
    std::vector<InlineSyntaxTree> extra_trees;

    SyntaxLayer() = default;
    SyntaxLayer(const SyntaxLayer&) = delete;
    SyntaxLayer& operator=(const SyntaxLayer&) = delete;
    SyntaxLayer(SyntaxLayer&& other) noexcept;
    SyntaxLayer& operator=(SyntaxLayer&& other) noexcept;
    ~SyntaxLayer();

    void clear_tree();
    void reset();

private:
    void move_from(SyntaxLayer& other) noexcept;
};

struct TextSession {
    TextPos cursor{};
    TextPos selection_anchor{};
    u32 scroll_row = 0;
    i32 scroll_cell = 0;
    i32 preferred_cell = 0;
    TextPos wrap_scroll{};
    bool wrap_end_affinity = false;
    TextByteIndex byte_index;

    LanguageId language = 0;
    SyntaxLayer primary_syntax;
    SyntaxLayer inline_syntax;

    TextRange selection() const;
};

void begin_text_syntax(TextSession& session, TextCardData& data);

TextEdit replace_text_content(
    TextCardData& data,
    TextSession* session,
    TextRange range,
    std::string_view inserted,
    bool styles_follow_old_text = true,
    TextStyleChange* style_change = nullptr
);
