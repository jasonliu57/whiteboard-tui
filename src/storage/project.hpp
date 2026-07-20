#pragma once

#include "binary.hpp"
#include "string_view_stream.hpp"
#include "version.hpp"
#include "../board.hpp"
#include "../edge_route.hpp"
#include "../formats/format.hpp"
#include "../formats/validation.hpp"
#include "../glyph_layer.hpp"
#include "../languages/ids.hpp"
#include "../spatial/board_spatial.hpp"

#include <algorithm>
#include <limits>
#include <optional>
#include <string>
#include <utility>
#include <vector>

constexpr u32 kCardsSection = 0x44524143;   // "CARD"
constexpr u32 kEdgesSection = 0x45474445;   // "EDGE"
constexpr u32 kGlyphsSection = 0x50594C47;  // "GLYP"
constexpr u32 kBoardSectionCount = 3;

static void write_edges(
    std::ostream& output,
    const Board& board
) {
    write_value(output, static_cast<u32>(board.edges.size()));

    for (const std::optional<Edge>& slot : board.edges) {
        write_value(output, static_cast<u8>(slot.has_value()));

        if (!slot.has_value()) {
            continue;
        }

        const Edge& edge = *slot;
        write_value(output, edge.source.card);
        write_value(output, static_cast<u8>(edge.source.side));
        write_value(output, edge.target.card);
        write_value(output, static_cast<u8>(edge.target.side));
        write_value(output, static_cast<u8>(edge.mode));
        write_value(output, static_cast<u8>(edge.state));
        write_rect(output, edge.route_bounds);
        write_value(output, static_cast<u32>(edge.points.size()));

        for (Pos point : edge.points) {
            write_value(output, point.x);
            write_value(output, point.y);
        }
    }
}

static bool read_edges(
    ProjectReader& input,
    Board& board,
    const CardSpatial& spatial
) {
    const u32 slot_count = read_value<u32>(input);

    if (!input.count_fits(
            slot_count,
            sizeof(u8),
            kMaximumProjectSlots,
            sizeof(std::optional<Edge>) + 2 * sizeof(EdgeId)
        )) {
        return false;
    }

    board.edges.resize(slot_count);

    for (EdgeId id = 0; id < slot_count; ++id) {
        const u8 alive = read_value<u8>(input);

        if (alive > 1) {
            return false;
        }

        if (alive == 0) {
            continue;
        }

        Edge edge;
        edge.source.card = read_value<CardId>(input);
        const u8 source_side = read_value<u8>(input);
        edge.source.side = static_cast<PortSide>(source_side);
        edge.target.card = read_value<CardId>(input);
        const u8 target_side = read_value<u8>(input);
        edge.target.side = static_cast<PortSide>(target_side);
        const u8 mode = read_value<u8>(input);
        const u8 state = read_value<u8>(input);
        edge.mode = static_cast<RouteMode>(mode);
        edge.state = static_cast<RouteState>(state);

        edge.route_bounds = read_rect(input);

        const u32 point_count = read_value<u32>(input);

        constexpr u64 kPointBytes = sizeof(i64) * 2;

        if (!input.count_fits(
                point_count,
                kPointBytes,
                kMaximumEdgePoints,
                sizeof(Pos)
            )) {
            return false;
        }

        edge.points.reserve(point_count);

        for (u32 i = 0; i < point_count; ++i) {
            edge.points.push_back({
                read_value<i64>(input),
                read_value<i64>(input),
            });
        }

        if (
            !input ||
            edge.source.card >= board.cards.size() ||
            edge.target.card >= board.cards.size() ||
            edge.source.card == edge.target.card ||
            source_side > static_cast<u8>(PortSide::Left) ||
            target_side > static_cast<u8>(PortSide::Left) ||
            mode > static_cast<u8>(RouteMode::Manual) ||
            state > static_cast<u8>(RouteState::Blocked)
        ) {
            return false;
        }

        normalize_edge_points(edge.points);

        if (!edge_route_bounds_valid(edge.route_bounds)) {
            return false;
        }

        for (Pos point : edge.points) {
            if (
                point.x == std::numeric_limits<i64>::max() ||
                point.y == std::numeric_limits<i64>::max()
            ) {
                return false;
            }
        }

        if (!validate_edge_geometry(edge.points)) {
            return false;
        }

        edge.state = validate_edge_collision(
            board,
            spatial,
            edge.source,
            &edge.target,
            edge.points
        )
            ? RouteState::Ready
            : RouteState::Blocked;

        board.edges[id].emplace(std::move(edge));
        ++board.live_edges;
        board.attach_edge(id);
    }
    return static_cast<bool>(input);
}

static void write_glyphs(
    std::ostream& output,
    const GlyphLayer& glyphs
) {
    write_value(output, static_cast<u32>(glyphs.cells.size()));

    std::vector<GlyphCell> ordered;
    ordered.reserve(glyphs.cells.size());
    for (const auto& [pos, glyph] : glyphs.cells) ordered.push_back({pos, glyph});
    std::sort(ordered.begin(), ordered.end(), [](const GlyphCell& a, const GlyphCell& b) {
        return a.pos.y != b.pos.y ? a.pos.y < b.pos.y : a.pos.x < b.pos.x;
    });
    for (const GlyphCell& cell : ordered) {
        write_value(output, cell.pos.x);
        write_value(output, cell.pos.y);
        write_value(output, static_cast<u32>(cell.glyph));
    }
}

static bool read_glyphs(
    ProjectReader& input,
    GlyphLayer& glyphs
) {
    const u32 count = read_value<u32>(input);

    constexpr u64 kGlyphBytes = sizeof(i64) * 2 + sizeof(u32);

    constexpr u64 kGlyphAllocationBytes =
        sizeof(Pos) + sizeof(char32_t) + 2 * sizeof(void*);

    if (!input.count_fits(
            count,
            kGlyphBytes,
            kMaximumProjectItems,
            kGlyphAllocationBytes
        )) {
        return false;
    }

    glyphs.cells.reserve(count);

    for (u32 i = 0; i < count; ++i) {
        const Pos pos{
            read_value<i64>(input),
            read_value<i64>(input),
        };
        const char32_t glyph = static_cast<char32_t>(
            read_value<u32>(input)
        );

        if (
            !input ||
            !glyphs.insert(pos, glyph)
        ) {
            return false;
        }
    }

    return true;
}

static void write_cards(
    std::ostream& output,
    const Board& board
) {
    write_value(output, static_cast<u32>(board.cards.size()));

    for (const std::optional<Card>& slot : board.cards) {
        write_value(output, static_cast<u8>(slot.has_value()));

        if (!slot.has_value()) {
            continue;
        }

        const Card& card = *slot;
        write_value(output, card.pos.x);
        write_value(output, card.pos.y);
        write_value(output, card.static_format);
        write_card_data(
            output,
            card.data
        );
    }
}

static bool read_cards(
    ProjectReader& input,
    Board& board,
    CardSpatial& spatial,
    const CardFormats& formats
) {
    const u32 slot_count = read_value<u32>(input);

    if (!input.count_fits(
            slot_count,
            sizeof(u8),
            kMaximumProjectSlots,
            sizeof(std::optional<Card>) +
                sizeof(absl::InlinedVector<EdgeId, 4>) +
                sizeof(CardSpatialSlot) +
                sizeof(u32)
        )) {
        return false;
    }

    Board loaded;
    CardSpatial loaded_spatial;
    loaded.cards.resize(slot_count);
    loaded.incident.resize(slot_count);
    loaded_spatial.reset_slots(slot_count);
    u32 live_cards = 0;

    for (CardId id = 0; id < slot_count; ++id) {
        const u8 alive = read_value<u8>(input);

        if (alive > 1) {
            return false;
        }

        if (alive == 0) {
            continue;
        }

        Card card;
        card.pos.x = read_value<i64>(input);
        card.pos.y = read_value<i64>(input);
        card.static_format = read_value<StaticFormatId>(input);
        if (!input || card.static_format >= formats.size()) {
            return false;
        }
        const CardFormat& format = formats[card.static_format];
        if (!read_card_data(input, format.data_kind, card.data)) {
            return false;
        }
        format.rebuild(card.data);
        if (auto* text = std::get_if<TextCardData>(&card.data);
            text != nullptr && (text->language == kMarkdownLanguageId ||
                                text->language == kCppLanguageId)) {
            TextSession syntax;
            begin_text_syntax(syntax, *text);
        }

        const Extent extent = format.measure(card.data);
        Rect rect;

        if (
            !card_data_matches(format.data_kind, card.data) ||
            !extent_in_format(extent, format) ||
            !checked_rect_at(card.pos, extent, rect)
        ) {
            return false;
        }

        u64 cell_count = 0;
        constexpr u64 kSpatialMembershipAllocationBytes =
            sizeof(CardId) +
            sizeof(CardSpatialCell) +
            sizeof(CardSpatial::Bucket) +
            2 * sizeof(void*);

        if (
            !card_spatial_cell_count(rect, cell_count) ||
            cell_count >
                std::numeric_limits<u64>::max() /
                    kSpatialMembershipAllocationBytes ||
            !input.claim_allocation(
                cell_count * kSpatialMembershipAllocationBytes
            )
        ) {
            return false;
        }

        loaded.cards[id].emplace(std::move(card));
        loaded_spatial.change(id, rect);
        ++live_cards;
    }

    loaded.live_cards = live_cards;
    board = std::move(loaded);
    spatial = std::move(loaded_spatial);
    return static_cast<bool>(input);
}

template<class Write>
static bool write_project_section(
    std::ostream& output,
    u32 tag,
    std::string& buffer,
    Write&& write,
    u64* remaining_bytes = nullptr
) {
    buffer.clear();
    StringAppendOutputStream section(buffer);
    write(section);
    section.flush();

    if (!section || buffer.size() > kMaximumProjectBytes) {
        return false;
    }

    const u64 section_bytes = sizeof(u32) * 2 + sizeof(u64) + buffer.size();
    if (remaining_bytes != nullptr) {
        if (section_bytes > *remaining_bytes) {
            return false;
        }
        *remaining_bytes -= section_bytes;
    }

    write_value(output, tag);
    write_value(output, static_cast<u64>(buffer.size()));
    write_value(output, project_crc32(buffer.data(), buffer.size()));
    write_bytes(output, buffer.data(), buffer.size());
    return static_cast<bool>(output);
}

template<class Read>
static bool read_project_section(
    ProjectReader& input,
    u32 expected_tag,
    Read&& read
) {
    const u32 tag = read_value<u32>(input);
    const u64 size = read_value<u64>(input);
    const u32 expected_checksum = read_value<u32>(input);

    if (
        !input ||
        tag != expected_tag ||
        size > kMaximumProjectBytes ||
        !input.can_read(size)
    ) {
        input.reject();
        return false;
    }

    ProjectReader section(input, size, true);

    if (
        !read(section) ||
        !section ||
        section.remaining() != 0 ||
        section.checksum() != expected_checksum
    ) {
        input.reject();
        return false;
    }

    return true;
}

static bool write_main_file_content(
    std::ostream& output,
    const Board& board,
    const GlyphLayer& glyphs
) {
    write_value(output, kBoardMagic);
    write_value(output, kBoardFormatId);
    write_value(output, kBoardSectionCount);
    std::string section_buffer;
    u64 remaining_bytes = kMaximumProjectBytes - 3 * sizeof(u32);
    constexpr u64 kMinimumSerializedLiveEdgeBytes = 80;
    constexpr u64 kMaximumAutomaticSectionReserve =
        64ULL * 1024ULL * 1024ULL;
    const u64 edge_slots = board.edges.size();
    const u64 live_edges = board.live_edges;

    if (
        edge_slots <=
            kMaximumAutomaticSectionReserve - sizeof(u32) &&
        live_edges <=
            (kMaximumAutomaticSectionReserve - sizeof(u32) - edge_slots) /
                kMinimumSerializedLiveEdgeBytes
    ) {
        section_buffer.reserve(static_cast<std::size_t>(
            sizeof(u32) +
            edge_slots +
            live_edges * kMinimumSerializedLiveEdgeBytes
        ));
    }

    if (
        !write_project_section(
            output,
            kCardsSection,
            section_buffer,
            [&](std::ostream& section) {
                write_cards(section, board);
            },
            &remaining_bytes
        ) ||
        !write_project_section(
            output,
            kEdgesSection,
            section_buffer,
            [&](std::ostream& section) {
                write_edges(section, board);
            },
            &remaining_bytes
        ) ||
        !write_project_section(
            output,
            kGlyphsSection,
            section_buffer,
            [&](std::ostream& section) {
                write_glyphs(section, glyphs);
            },
            &remaining_bytes
        )
    ) {
        return false;
    }

    return static_cast<bool>(output);
}

// Pure decoder: no filename, external content, recovery, or filesystem writes.
static inline bool read_main_file_content(
    std::istream& stream,
    u64 size,
    Board& board,
    CardSpatial& spatial,
    GlyphLayer& glyphs,
    const CardFormats& formats,
    std::string* error = nullptr,
    u64 allocation_budget = kMaximumProjectAllocationBytes
) {
    if (size > kMaximumProjectBytes) return false;
    ProjectReader input(stream, size, std::min(allocation_budget, kMaximumProjectAllocationBytes));
    if (error != nullptr) *error = "invalid or damaged project";
    const u32 magic = read_value<u32>(input);
    const u32 format_id = read_value<u32>(input);

    if (
        !input ||
        magic != kBoardMagic ||
        format_id != kBoardFormatId
    ) {
        return false;
    }

    Board loaded;
    CardSpatial loaded_spatial;
    GlyphLayer loaded_glyphs;

    const u32 section_count = read_value<u32>(input);

    if (section_count != kBoardSectionCount) {
        return false;
    }

    if (
        !read_project_section(
            input,
            kCardsSection,
            [&](ProjectReader& section) {
                return read_cards(
                    section,
                    loaded,
                    loaded_spatial,
                    formats
                );
            }
        ) ||
        !read_project_section(
            input,
            kEdgesSection,
            [&](ProjectReader& section) {
                return read_edges(
                    section,
                    loaded,
                    loaded_spatial
                );
            }
        ) ||
        !read_project_section(
            input,
            kGlyphsSection,
            [&](ProjectReader& section) {
                return read_glyphs(section, loaded_glyphs);
            }
        )
    ) {
        return false;
    }

    if (!input || input.remaining() != 0) {
        return false;
    }

    board = std::move(loaded);
    spatial = std::move(loaded_spatial);
    glyphs = std::move(loaded_glyphs);
    if (error != nullptr) error->clear();
    return true;
}
