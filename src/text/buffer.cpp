#include "buffer.hpp"

#include "utf8.hpp"

#include <algorithm>
#include <iterator>
#include <limits>
#include <string>
#include <string_view>

void TextByteIndex::rebuild(const TextLines& lines) {
    const std::size_t count =
        (lines.size() + kRowsPerBlock - 1) / kRowsPerBlock;
    block_bytes_.assign(count, 0);

    for (std::size_t row = 0; row < lines.size(); ++row) {
        block_bytes_[row / kRowsPerBlock] +=
            static_cast<u64>(lines[row].size()) + 1;
    }

    rebuild_fenwick();
    line_count_ = lines.size();
}

u32 TextByteIndex::row_start(const TextLines& lines, u32 row) const {
    const u32 bounded_row = static_cast<u32>(std::min<std::size_t>(
        row,
        lines.size()
    ));

    if (line_count_ != lines.size() || row > lines.size()) {
        return scanned_row_start(lines, bounded_row);
    }

    const std::size_t block = row / kRowsPerBlock;
    u64 offset = prefix_blocks(block);
    const std::size_t first = block * kRowsPerBlock;

    for (std::size_t current = first; current < row; ++current) {
        offset += static_cast<u64>(lines[current].size()) + 1;
    }

    return static_cast<u32>(offset);
}

void TextByteIndex::after_edit(
    const TextLines& lines,
    const TextEdit& edit
) {
    const u32 old_rows =
        edit.old_range.end.row - edit.old_range.begin.row;
    const u32 new_rows = edit.new_end.row - edit.old_range.begin.row;

    if (old_rows != new_rows || line_count_ != lines.size()) {
        rebuild(lines);
        return;
    }

    if (block_bytes_.empty()) {
        rebuild(lines);
        return;
    }

    const std::size_t first_block =
        edit.old_range.begin.row / kRowsPerBlock;
    const std::size_t last_block = edit.new_end.row / kRowsPerBlock;

    if (
        first_block == last_block &&
        first_block < block_bytes_.size()
    ) {
        if (edit.new_end_byte > edit.old_end_byte) {
            const u64 delta = edit.new_end_byte - edit.old_end_byte;
            block_bytes_[first_block] += delta;
            add_to_fenwick(first_block, delta);
        } else if (edit.old_end_byte > edit.new_end_byte) {
            const u64 delta = edit.old_end_byte - edit.new_end_byte;
            block_bytes_[first_block] -= delta;
            subtract_from_fenwick(first_block, delta);
        }

        return;
    }

    for (std::size_t block = first_block;
         block <= last_block && block < block_bytes_.size();
         ++block) {
        refresh_block(lines, block);
    }
}

u32 TextByteIndex::scanned_row_start(
    const TextLines& lines,
    u32 row
) {
    u64 offset = 0;

    for (u32 current = 0; current < row; ++current) {
        offset += static_cast<u64>(lines[current].size()) + 1;
    }

    return static_cast<u32>(offset);
}

void TextByteIndex::rebuild_fenwick() {
    fenwick_.assign(block_bytes_.size() + 1, 0);

    for (std::size_t block = 0; block < block_bytes_.size(); ++block) {
        const std::size_t index = block + 1;
        fenwick_[index] += block_bytes_[block];
        const std::size_t parent = index + (index & (~index + 1));

        if (parent < fenwick_.size()) {
            fenwick_[parent] += fenwick_[index];
        }
    }
}

void TextByteIndex::add_to_fenwick(std::size_t block, u64 value) {
    for (std::size_t index = block + 1;
         index < fenwick_.size();
         index += index & (~index + 1)) {
        fenwick_[index] += value;
    }
}

void TextByteIndex::subtract_from_fenwick(
    std::size_t block,
    u64 value
) {
    for (std::size_t index = block + 1;
         index < fenwick_.size();
         index += index & (~index + 1)) {
        fenwick_[index] -= value;
    }
}

u64 TextByteIndex::prefix_blocks(std::size_t block) const {
    u64 result = 0;

    for (std::size_t index = block; index != 0; index &= index - 1) {
        result += fenwick_[index];
    }

    return result;
}

void TextByteIndex::refresh_block(
    const TextLines& lines,
    std::size_t block
) {
    const std::size_t first = block * kRowsPerBlock;
    const std::size_t last = std::min(
        lines.size(),
        first + kRowsPerBlock
    );
    u64 next = 0;

    for (std::size_t row = first; row < last; ++row) {
        next += static_cast<u64>(lines[row].size()) + 1;
    }

    const u64 previous = block_bytes_[block];

    if (next > previous) {
        add_to_fenwick(block, next - previous);
    } else if (previous > next) {
        subtract_from_fenwick(block, previous - next);
    }

    block_bytes_[block] = next;
}

static bool text_pos_less(TextPos lhs, TextPos rhs) {
    return
        lhs.row < rhs.row ||
        (lhs.row == rhs.row && lhs.byte < rhs.byte);
}

TextRange ordered_range(TextPos first, TextPos second) {
    return text_pos_less(second, first)
        ? TextRange{second, first}
        : TextRange{first, second};
}

bool text_range_contains(TextRange range, TextPos position) {
    return
        !text_pos_less(position, range.begin) &&
        text_pos_less(position, range.end);
}

std::string extract_text(
    const TextLines& lines,
    TextRange range
) {
    if (range.begin.row == range.end.row) {
        return lines[range.begin.row].substr(
            range.begin.byte,
            range.end.byte - range.begin.byte
        );
    }

    std::size_t size =
        lines[range.begin.row].size() - range.begin.byte + 1 +
        range.end.byte;

    for (u32 row = range.begin.row + 1;
         row < range.end.row;
         ++row) {
        size += lines[row].size() + 1;
    }

    std::string result;
    result.reserve(size);
    result.append(lines[range.begin.row], range.begin.byte);

    for (u32 row = range.begin.row + 1;
         row < range.end.row;
         ++row) {
        result.push_back('\n');
        result.append(lines[row]);
    }

    result.push_back('\n');
    result.append(lines[range.end.row], 0, range.end.byte);
    return result;
}

PreparedTextEdit prepare_text_edit(
    const TextLines& lines,
    TextRange range,
    std::string_view inserted,
    const TextByteIndex* byte_index
) {
    PreparedTextEdit prepared;
    prepared.edit.old_range = range;
    prepared.edit.start_byte =
        (byte_index == nullptr
            ? TextByteIndex{}.row_start(lines, range.begin.row)
            : byte_index->row_start(lines, range.begin.row)) +
        range.begin.byte;

    prepared.edit.old_end_byte = prepared.edit.start_byte;

    if (range.begin.row == range.end.row) {
        prepared.edit.old_end_byte +=
            range.end.byte - range.begin.byte;
    } else {
        prepared.edit.old_end_byte += static_cast<u32>(
            lines[range.begin.row].size() - range.begin.byte + 1
        );

        for (u32 row = range.begin.row + 1;
             row < range.end.row;
             ++row) {
            prepared.edit.old_end_byte +=
                static_cast<u32>(lines[row].size()) + 1;
        }

        prepared.edit.old_end_byte += range.end.byte;
    }

    prepared.edit.new_end_byte =
        prepared.edit.start_byte + static_cast<u32>(inserted.size());
    for (std::size_t begin = 0;;) {
        const std::size_t end = inserted.find('\n', begin);

        if (end == std::string_view::npos) {
            prepared.inserted_lines.emplace_back(
                inserted.substr(begin)
            );
            break;
        }

        prepared.inserted_lines.emplace_back(
            inserted.substr(begin, end - begin)
        );
        begin = end + 1;
    }

    prepared.edit.new_end = prepared.inserted_lines.size() == 1
        ? TextPos{
            range.begin.row,
            range.begin.byte + static_cast<u32>(
                prepared.inserted_lines.front().size()
            )
        }
        : TextPos{
            range.begin.row + static_cast<u32>(
                prepared.inserted_lines.size() - 1
            ),
            static_cast<u32>(prepared.inserted_lines.back().size())
        };
    return prepared;
}

void apply_text_edit(
    TextLines& lines,
    PreparedTextEdit&& prepared
) {
    const TextRange range = prepared.edit.old_range;

    if (
        range.begin.row == range.end.row &&
        prepared.inserted_lines.size() == 1
    ) {
        lines[range.begin.row].replace(
            range.begin.byte,
            range.end.byte - range.begin.byte,
            prepared.inserted_lines.front()
        );
        return;
    }

    std::string suffix;

    if (range.begin.row == range.end.row) {
        suffix = lines[range.end.row].substr(range.end.byte);
    } else {
        suffix = std::move(lines[range.end.row]);
        suffix.erase(0, range.end.byte);
    }

    lines[range.begin.row].erase(range.begin.byte);

    if (range.end.row > range.begin.row) {
        lines.erase(
            lines.begin() + range.begin.row + 1,
            lines.begin() + range.end.row + 1
        );
    }

    if (prepared.inserted_lines.size() == 1) {
        lines[range.begin.row].append(prepared.inserted_lines.front());
        lines[range.begin.row].append(suffix);
        return;
    }

    lines[range.begin.row].append(prepared.inserted_lines.front());
    prepared.inserted_lines.back().append(suffix);

    lines.insert(
        lines.begin() + range.begin.row + 1,
        std::make_move_iterator(prepared.inserted_lines.begin() + 1),
        std::make_move_iterator(prepared.inserted_lines.end())
    );
}

i32 cell_column(const std::string& line, u32 target_byte) {
    target_byte = static_cast<u32>(std::min<std::size_t>(
        target_byte,
        line.size()
    ));
    i32 cells = 0;

    for (u32 byte = 0; byte < target_byte;) {
        const unsigned char current = static_cast<unsigned char>(line[byte]);

        if (current >= 0x20U && current <= 0x7EU) {
            ++cells;
            ++byte;
            continue;
        }

        const Rune rune = decode_utf8(line, byte);

        if (rune.codepoint == U'\t') {
            cells += 4 - (cells % 4);
        } else {
            cells += display_rune(rune.codepoint).width;
        }

        byte += rune.bytes;
    }

    return cells;
}

u32 next_text_cluster_byte(
    const std::string& line,
    u32 byte
) {
    if (byte >= line.size()) {
        return static_cast<u32>(line.size());
    }

    byte += decode_utf8(line, byte).bytes;

    while (byte < line.size()) {
        const Rune rune = decode_utf8(line, byte);

        if (!unicode_mark(rune.codepoint)) {
            break;
        }

        byte += rune.bytes;
    }

    return byte;
}

u32 previous_text_cluster_byte(
    const std::string& line,
    u32 byte
) {
    u32 begin = previous_utf8_byte(line, byte);

    while (
        begin > 0 &&
        unicode_mark(decode_utf8(line, begin).codepoint)
    ) {
        begin = previous_utf8_byte(line, begin);
    }

    return begin;
}

u32 byte_at_cell(const std::string& line, i32 target_cell) {
    i32 cell = 0;

    for (u32 byte = 0; byte < line.size();) {
        if (target_cell <= cell) {
            return byte;
        }

        const u32 end = next_text_cluster_byte(line, byte);
        i32 width = 0;

        for (u32 cluster_byte = byte;
             cluster_byte < end;) {
            const Rune rune = decode_utf8(line, cluster_byte);
            width += rune.codepoint == U'\t'
                ? 4 - ((cell + width) % 4)
                : display_rune(rune.codepoint).width;
            cluster_byte += rune.bytes;
        }

        if (target_cell < cell + width) {
            return byte;
        }

        cell += width;
        byte = end;
    }

    return static_cast<u32>(line.size());
}

u32 previous_utf8_byte(const std::string& line, u32 byte) {
    byte = static_cast<u32>(std::min<std::size_t>(byte, line.size()));

    if (byte == 0) {
        return 0;
    }

    --byte;

    while (
        byte > 0 &&
        (static_cast<u8>(line[byte]) & 0xC0) == 0x80
    ) {
        --byte;
    }

    return byte;
}
