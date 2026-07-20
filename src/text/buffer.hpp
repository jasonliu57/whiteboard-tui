#pragma once

#include "../model.hpp"

#include <absl/container/inlined_vector.h>

#include <cstddef>
#include <string>
#include <string_view>
#include <vector>

struct TextPos {
    u32 row = 0;
    u32 byte = 0;

    friend bool operator==(const TextPos&, const TextPos&) = default;
};

struct TextRange {
    TextPos begin;
    TextPos end;
};

struct TextEdit {
    TextRange old_range{};
    TextPos new_end{};
    u32 start_byte = 0;
    u32 old_end_byte = 0;
    u32 new_end_byte = 0;
};

class TextByteIndex {
public:
    static constexpr u32 kRowsPerBlock = 256;

    void rebuild(const TextLines& lines);
    u32 row_start(const TextLines& lines, u32 row) const;
    void after_edit(const TextLines& lines, const TextEdit& edit);

private:
    absl::InlinedVector<u64, 4> block_bytes_;
    absl::InlinedVector<u64, 5> fenwick_;
    std::size_t line_count_ = 0;

    static u32 scanned_row_start(const TextLines& lines, u32 row);
    void rebuild_fenwick();
    void add_to_fenwick(std::size_t block, u64 value);
    void subtract_from_fenwick(std::size_t block, u64 value);
    u64 prefix_blocks(std::size_t block) const;
    void refresh_block(const TextLines& lines, std::size_t block);
};

struct PreparedTextEdit {
    TextEdit edit;
    absl::InlinedVector<std::string, 2> inserted_lines;
};

TextRange ordered_range(TextPos first, TextPos second);

bool text_range_contains(TextRange range, TextPos position);

std::string extract_text(const TextLines& lines, TextRange range);

PreparedTextEdit prepare_text_edit(
    const TextLines& lines,
    TextRange range,
    std::string_view inserted,
    const TextByteIndex* byte_index = nullptr
);

void apply_text_edit(TextLines& lines, PreparedTextEdit&& prepared);
i32 cell_column(const std::string& line, u32 target_byte);
u32 next_text_cluster_byte(const std::string& line, u32 byte);
u32 previous_utf8_byte(const std::string& line, u32 byte);
u32 previous_text_cluster_byte(const std::string& line, u32 byte);
u32 byte_at_cell(const std::string& line, i32 target_cell);
