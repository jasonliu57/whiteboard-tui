#pragma once

#include "../formats/format.hpp"
#include "limits.hpp"

#include <array>
#include <cstdint>
#include <istream>
#include <limits>
#include <ostream>
#include <streambuf>
#include <string>
#include <type_traits>
#include <utility>
#include <vector>

inline constexpr std::array<std::array<u32, 256>, 8>
kProjectCrc32Tables = [] {
    std::array<std::array<u32, 256>, 8> tables{};

    for (u32 byte = 0; byte < tables[0].size(); ++byte) {
        u32 checksum = byte;

        for (u8 bit = 0; bit < 8; ++bit) {
            checksum = (checksum >> 1) ^
                (0xEDB88320U & (0U - (checksum & 1U)));
        }

        tables[0][byte] = checksum;
    }

    for (std::size_t slice = 1; slice < tables.size(); ++slice) {
        for (u32 byte = 0; byte < tables[slice].size(); ++byte) {
            const u32 previous = tables[slice - 1][byte];
            tables[slice][byte] = (previous >> 8) ^
                tables[0][previous & 0xFFU];
        }
    }

    return tables;
}();

static u32 update_project_crc32(
    u32 checksum,
    const void* data,
    std::size_t size
) noexcept {
    const auto* bytes = static_cast<const unsigned char*>(data);
    std::size_t offset = 0;

    while (size - offset >= 8) {
        const u32 first = checksum ^ (
            static_cast<u32>(bytes[offset]) |
            (static_cast<u32>(bytes[offset + 1]) << 8) |
            (static_cast<u32>(bytes[offset + 2]) << 16) |
            (static_cast<u32>(bytes[offset + 3]) << 24)
        );
        const u32 second =
            static_cast<u32>(bytes[offset + 4]) |
            (static_cast<u32>(bytes[offset + 5]) << 8) |
            (static_cast<u32>(bytes[offset + 6]) << 16) |
            (static_cast<u32>(bytes[offset + 7]) << 24);
        checksum =
            kProjectCrc32Tables[7][first & 0xFFU] ^
            kProjectCrc32Tables[6][(first >> 8) & 0xFFU] ^
            kProjectCrc32Tables[5][(first >> 16) & 0xFFU] ^
            kProjectCrc32Tables[4][first >> 24] ^
            kProjectCrc32Tables[3][second & 0xFFU] ^
            kProjectCrc32Tables[2][(second >> 8) & 0xFFU] ^
            kProjectCrc32Tables[1][(second >> 16) & 0xFFU] ^
            kProjectCrc32Tables[0][second >> 24];
        offset += 8;
    }

    if (size - offset >= 4) {
        checksum ^=
            static_cast<u32>(bytes[offset]) |
            (static_cast<u32>(bytes[offset + 1]) << 8) |
            (static_cast<u32>(bytes[offset + 2]) << 16) |
            (static_cast<u32>(bytes[offset + 3]) << 24);
        checksum =
            kProjectCrc32Tables[3][checksum & 0xFFU] ^
            kProjectCrc32Tables[2][(checksum >> 8) & 0xFFU] ^
            kProjectCrc32Tables[1][(checksum >> 16) & 0xFFU] ^
            kProjectCrc32Tables[0][checksum >> 24];
        offset += 4;
    }

    for (; offset < size; ++offset) {
        checksum = (checksum >> 8) ^
            kProjectCrc32Tables[0][
                (checksum ^ bytes[offset]) & 0xFFU
            ];
    }

    return checksum;
}

static u32 project_crc32(const void* data, std::size_t size) noexcept {
    return update_project_crc32(0xFFFFFFFFU, data, size) ^ 0xFFFFFFFFU;
}

class ProjectReader {
public:
    ProjectReader(
        std::istream& input,
        u64 size,
        u64 allocation_budget = kMaximumProjectAllocationBytes
    )
        : input_(&input),
          remaining_(size),
          allocation_budget_(allocation_budget) {}

    ProjectReader(ProjectReader& parent, u64 size, bool checksum)
        : input_(parent.input_),
          parent_(&parent),
          remaining_(size),
          checksum_enabled_(checksum) {
        if (!parent.can_read(size)) {
            reject();
            parent.reject();
        }
    }

    ProjectReader(const ProjectReader&) = delete;
    ProjectReader& operator=(const ProjectReader&) = delete;

    bool read(void* destination, std::size_t size) {
        if (!can_read(size)) {
            reject();
            return false;
        }

        if (!*input_) {
            failed_ = true;
            return false;
        }

        const auto requested = static_cast<std::streamsize>(size);
        const std::streamsize received = input_->rdbuf()->sgetn(
            static_cast<char*>(destination),
            requested
        );

        if (received != requested) {
            input_->setstate(std::ios::eofbit | std::ios::failbit);
            failed_ = true;
            return false;
        }

        remaining_ -= size;

        if (parent_ != nullptr) {
            parent_->consume_from_child(size);
        }

        if (checksum_enabled_) {
            checksum_ = update_project_crc32(
                checksum_,
                destination,
                size
            );
        }

        return true;
    }

    bool can_read(u64 size) const noexcept {
        return !failed_ && size <= remaining_;
    }

    bool count_fits(
        u64 count,
        u64 minimum_item_bytes,
        u64 semantic_limit,
        u64 allocation_item_bytes
    ) {
        if (
            count > semantic_limit ||
            (minimum_item_bytes != 0 &&
             count > remaining_ / minimum_item_bytes) ||
            (allocation_item_bytes != 0 &&
             count >
                std::numeric_limits<u64>::max() /
                    allocation_item_bytes)
        ) {
            reject();
            return false;
        }

        return claim_allocation(count * allocation_item_bytes);
    }

    bool claim_allocation(u64 size) {
        if (parent_ != nullptr) {
            if (!parent_->claim_allocation(size)) {
                reject();
                return false;
            }

            return true;
        }

        if (size > allocation_budget_) {
            reject();
            return false;
        }

        allocation_budget_ -= size;
        return true;
    }

    u64 remaining() const noexcept {
        return remaining_;
    }

    bool good() const noexcept {
        return !failed_ && static_cast<bool>(*input_);
    }

    explicit operator bool() const noexcept {
        return good();
    }

    u32 checksum() const noexcept {
        return checksum_ ^ 0xFFFFFFFFU;
    }

    void reject() noexcept {
        failed_ = true;
    }

private:
    std::istream* input_ = nullptr;
    ProjectReader* parent_ = nullptr;
    u64 remaining_ = 0;
    bool failed_ = false;
    bool checksum_enabled_ = false;
    u32 checksum_ = 0xFFFFFFFFU;
    u64 allocation_budget_ = 0;

    void consume_from_child(u64 size) noexcept {
        if (size > remaining_) {
            failed_ = true;
            return;
        }

        remaining_ -= size;

        if (parent_ != nullptr) {
            parent_->consume_from_child(size);
        }
    }
};

static void write_bytes(
    std::ostream& output,
    const char* data,
    std::size_t size
) {
    if (!output) {
        return;
    }

    const auto requested = static_cast<std::streamsize>(size);

    if (output.rdbuf()->sputn(data, requested) != requested) {
        output.setstate(std::ios::badbit);
    }
}

template<class T>
static void write_value(std::ostream& output, const T& value) {
    static_assert(std::is_integral_v<T>);
    using Unsigned = std::make_unsigned_t<T>;
    Unsigned bits = static_cast<Unsigned>(value);
    char bytes[sizeof(T)];

    for (std::size_t i = 0; i < sizeof(T); ++i) {
        bytes[i] = static_cast<char>(bits & 0xFFU);
        if constexpr (sizeof(T) > 1) {
            if (i + 1 < sizeof(T)) {
                bits >>= 8;
            }
        }
    }

    write_bytes(output, bytes, sizeof(bytes));
}

template<class T>
static T read_value(ProjectReader& input) {
    static_assert(std::is_integral_v<T>);
    using Unsigned = std::make_unsigned_t<T>;
    unsigned char bytes[sizeof(T)]{};

    if (!input.read(bytes, sizeof(bytes))) {
        return T{};
    }

    Unsigned bits = 0;

    for (std::size_t i = 0; i < sizeof(T); ++i) {
        bits |= static_cast<Unsigned>(bytes[i]) << (i * 8);
    }

    return static_cast<T>(bits);
}

static void write_string(
    std::ostream& output,
    std::string_view value
) {
    write_value(output, static_cast<u32>(value.size()));
    write_bytes(output, value.data(), value.size());
}

static std::string read_string(
    ProjectReader& input,
    u32 maximum_size = kMaximumProjectStringBytes
) {
    const u32 size = read_value<u32>(input);

    if (size > maximum_size || !input.can_read(size)) {
        input.reject();
        return {};
    }

    if (!input.claim_allocation(size)) {
        return {};
    }

    std::string value(size, '\0');

    if (size != 0) {
        input.read(value.data(), size);
    }

    return value;
}

static void write_style(std::ostream& output, Style style) {
    write_value(output, style.foreground);
    write_value(output, style.background);
    write_value(output, style.attributes);
}

static Style read_style(ProjectReader& input) {
    return {
        read_value<u8>(input),
        read_value<u8>(input),
        read_value<u8>(input)
    };
}

static void write_extent(std::ostream& output, Extent extent) {
    write_value(output, extent.width);
    write_value(output, extent.height);
}

static Extent read_extent(ProjectReader& input) {
    return {
        read_value<i32>(input),
        read_value<i32>(input)
    };
}

static void write_rect(std::ostream& output, Rect rect) {
    write_value(output, rect.left);
    write_value(output, rect.top);
    write_value(output, rect.right);
    write_value(output, rect.bottom);
}

static Rect read_rect(ProjectReader& input) {
    return {
        read_value<i64>(input),
        read_value<i64>(input),
        read_value<i64>(input),
        read_value<i64>(input),
    };
}

static void write_binary_lines(
    std::ostream& output,
    const TextLines& lines
) {
    write_value(output, static_cast<u32>(lines.size()));

    for (const std::string& line : lines) {
        write_string(output, line);
    }
}

static void read_binary_lines(
    ProjectReader& input,
    TextLines& lines
) {
    const u32 count = read_value<u32>(input);

    if (!input.count_fits(
            count,
            sizeof(u32),
            kMaximumProjectItems,
            sizeof(std::string)
        )) {
        return;
    }

    lines.clear();
    lines.reserve(count);

    for (u32 i = 0; i < count; ++i) {
        lines.push_back(read_string(input));
    }
}

static void write_text_spans(
    std::ostream& output,
    const TextStyles& spans
) {
    write_value(
        output,
        static_cast<u32>(text_style_span_count(spans))
    );

    for (const RowStyles& row : spans) {
        for (const TextSpan& span : row.spans) {
            write_value(output, row.row);
            write_value(output, span.begin_byte);
            write_value(output, span.end_byte);
            write_style(output, span.style);
        }
    }
}

static void read_text_spans(
    ProjectReader& input,
    TextStyles& spans
) {
    const u32 count = read_value<u32>(input);

    constexpr u64 kTextSpanBytes =
        sizeof(u32) * 3 + sizeof(u8) * 3;

    if (!input.count_fits(
            count,
            kTextSpanBytes,
            kMaximumProjectItems,
            sizeof(RowStyles) + sizeof(TextSpan)
        )) {
        return;
    }
    spans.clear();

    for (u32 i = 0; i < count; ++i) {
        const u32 row = read_value<u32>(input);
        TextSpan span{
            row,
            read_value<u32>(input),
            read_value<u32>(input),
            read_style(input),
        };

        if (spans.empty() || spans.back().row != row) {
            spans.emplace_back(row);
        }

        spans.back().spans.push_back(span);
    }
}

static void write_card_data(
    std::ostream& output,
    const CardData& card_data
) {
    if (const auto* data = std::get_if<TextCardData>(&card_data)) {
        write_extent(output, data->layout);
        write_value(output, data->language);
        write_text_spans(output, data->styles);

        write_binary_lines(output, data->lines);

        return;
    }

    if (const auto* data = std::get_if<TodoCardData>(&card_data)) {
        write_extent(output, data->layout);
        write_value(output, static_cast<u32>(data->items.size()));
        for (const TodoItem& item : data->items) {
            write_string(output, item.text);
            write_value(output, static_cast<u8>(item.done));
            write_style(output, item.style);
        }
        return;
    }

    if (const auto* data = std::get_if<FolderCardData>(&card_data)) {
        write_extent(output, data->layout);
        write_string(output, data->name);
        write_value(
            output,
            static_cast<u32>(data->entries.size())
        );

        for (const FolderEntry& entry : data->entries) {
            write_value(output, static_cast<u8>(entry.kind));
            write_value(output, entry.depth);
            write_string(output, entry.name);
            write_value(output, entry.target);
            write_value(output, static_cast<u8>(entry.collapsed));
        }

        return;
    }

    const CsvCardData& data = std::get<CsvCardData>(card_data);
    write_extent(output, data.layout);
    write_value(output, static_cast<u32>(data.column_widths.size()));

    for (i32 width : data.column_widths) {
        write_value(output, width);
    }

    write_value(output, static_cast<u32>(data.styled_cells.size()));

    for (const CsvCellStyle& cell : data.styled_cells) {
        write_value(output, cell.row);
        write_value(output, cell.column);
        write_style(output, cell.style);
    }

    write_value(output, static_cast<u32>(data.cells.size()));

    for (const auto& row : data.cells) {
        write_value(output, static_cast<u32>(row.size()));

        for (const std::string& cell : row) {
            write_string(output, cell);
        }
    }
}

static bool read_card_data(
    ProjectReader& input,
    CardDataKind kind,
    CardData& card_data
) {
    if (kind == CardDataKind::Text) {
        TextCardData data;
        data.layout = read_extent(input);
        data.language = read_value<LanguageId>(input);
        read_text_spans(input, data.styles);

        read_binary_lines(input, data.lines);

        card_data = std::move(data);
        return static_cast<bool>(input);
    }

    if (kind == CardDataKind::Todo) {
        TodoCardData data;
        data.layout = read_extent(input);
        const u32 count = read_value<u32>(input);
        if (!input.count_fits(count, sizeof(u32) + 4 * sizeof(u8),
                              kMaximumProjectItems, sizeof(TodoItem))) {
            return false;
        }
        data.items.clear();
        data.items.reserve(count);
        for (u32 i = 0; i < count; ++i) {
            std::string text = read_string(input);
            const u8 done = read_value<u8>(input);
            const Style style = read_style(input);
            if (!input || done > 1) {
                return false;
            }
            TodoItem item{std::move(text), done != 0};
            item.style = style;
            data.items.push_back(std::move(item));
        }
        card_data = std::move(data);
        return static_cast<bool>(input);
    }

    if (kind == CardDataKind::Folder) {
        FolderCardData data;
        data.layout = read_extent(input);
        data.name = read_string(input);

        const u32 count = read_value<u32>(input);

        constexpr u64 kMinimumFolderEntryBytes =
            sizeof(u8) + sizeof(u32) + sizeof(u32) +
            sizeof(CardId) + sizeof(u8);

        if (!input.count_fits(
                count,
                kMinimumFolderEntryBytes,
                kMaximumProjectItems,
                sizeof(FolderEntry)
            )) {
            return false;
        }

        data.entries.clear();
        data.entries.reserve(count);

        for (u32 i = 0; i < count; ++i) {
            const u8 kind_value = read_value<u8>(input);
            const u32 depth = read_value<u32>(input);
            std::string name = read_string(input);
            const CardId target = read_value<CardId>(input);
            const u8 collapsed = read_value<u8>(input);

            if (
                kind_value > static_cast<u8>(FolderEntryKind::Card) ||
                collapsed > 1
            ) {
                return false;
            }

            data.entries.push_back({
                static_cast<FolderEntryKind>(kind_value),
                depth,
                std::move(name),
                target,
                collapsed != 0,
            });
        }

        card_data = std::move(data);
        return static_cast<bool>(input);
    }

    CsvCardData data;
    data.layout = read_extent(input);

    const u32 width_count = read_value<u32>(input);

    if (!input.count_fits(
            width_count,
            sizeof(i32),
            kMaximumProjectItems,
            sizeof(i32)
        )) {
        return false;
    }

    data.column_widths.clear();
    data.column_widths.reserve(width_count);

    for (u32 i = 0; i < width_count; ++i) {
        data.column_widths.push_back(read_value<i32>(input));
    }

    const u32 style_count = read_value<u32>(input);

    constexpr u64 kCsvCellStyleBytes =
        sizeof(u32) * 2 + sizeof(u8) * 3;

    if (!input.count_fits(
            style_count,
            kCsvCellStyleBytes,
            kMaximumProjectItems,
            sizeof(CsvCellStyle)
        )) {
        return false;
    }

    data.styled_cells.clear();
    data.styled_cells.reserve(style_count);

    for (u32 i = 0; i < style_count; ++i) {
        data.styled_cells.push_back({
            read_value<u32>(input),
            read_value<u32>(input),
            read_style(input)
        });
    }

    const u32 row_count = read_value<u32>(input);

    if (!input.count_fits(
            row_count,
            sizeof(u32),
            kMaximumProjectItems,
            sizeof(std::vector<std::string>)
        )) {
        return false;
    }

    data.cells.clear();
    data.cells.reserve(row_count);

    for (u32 row = 0; row < row_count; ++row) {
        const u32 column_count = read_value<u32>(input);

        if (!input.count_fits(
                column_count,
                sizeof(u32),
                kMaximumProjectItems,
                sizeof(std::string)
            )) {
            return false;
        }

        std::vector<std::string> cells;
        cells.reserve(column_count);

        for (u32 column = 0; column < column_count; ++column) {
            cells.push_back(read_string(input));
        }

        data.cells.push_back(std::move(cells));
    }

    card_data = std::move(data);
    return static_cast<bool>(input);
}
