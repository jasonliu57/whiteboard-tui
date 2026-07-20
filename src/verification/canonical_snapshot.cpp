#include "canonical_snapshot.hpp"

#include "../decimal.hpp"
#include "../storage/api.hpp"
#include "../storage/string_view_stream.hpp"

#include <algorithm>
#include <limits>
#include <string_view>
#include <vector>

namespace whiteboard::verification {

namespace {

bool append_word(std::string& output, std::string_view word) {
    if (
        word.empty() ||
        word.find_first_of(" \t\r\n") != std::string_view::npos
    ) {
        return false;
    }

    output.append(word);
    return true;
}

template<class Integer>
void append_field(std::string& output, Integer value) {
    output.push_back(' ');
    append_decimal(output, value);
}

struct RecordCursor {
    std::uint32_t index = 0;
    std::uint32_t offset = 0;
};

constexpr std::uint64_t kCursorPartMask = UINT64_C(0xFFFFFFFF);

bool decode_cursor(
    std::uint64_t encoded,
    std::size_t record_count,
    RecordCursor& cursor
) {
    if (record_count > std::numeric_limits<std::uint32_t>::max()) {
        return false;
    }

    const std::uint64_t index = encoded >> 32;
    const std::uint64_t offset = encoded & kCursorPartMask;

    if (
        index > record_count ||
        (index == record_count && offset != 0)
    ) {
        return false;
    }

    cursor.index = static_cast<std::uint32_t>(index);
    cursor.offset = static_cast<std::uint32_t>(offset);
    return true;
}

std::uint64_t encode_cursor(RecordCursor cursor) {
    return
        static_cast<std::uint64_t>(cursor.index) << 32 |
        cursor.offset;
}

bool valid_cursor_phases(
    const Board& board,
    RecordCursor card,
    RecordCursor edge,
    RecordCursor glyph
) {
    if (
        card.index < board.cards.size() &&
        (edge.index != 0 || edge.offset != 0 ||
         glyph.index != 0 || glyph.offset != 0)
    ) {
        return false;
    }

    if (
        card.index == board.cards.size() &&
        edge.index < board.edges.size() &&
        (glyph.index != 0 || glyph.offset != 0)
    ) {
        return false;
    }

    return true;
}

enum class FragmentResult {
    Complete,
    PageFull,
    InvalidCursor,
    RecordTooLarge,
};

FragmentResult append_fragment(
    std::string& output,
    const std::string& record,
    std::size_t maximum_body_bytes,
    RecordCursor& cursor
) {
    if (record.size() > std::numeric_limits<std::uint32_t>::max()) {
        return FragmentResult::RecordTooLarge;
    }

    if (cursor.offset >= record.size()) {
        return FragmentResult::InvalidCursor;
    }

    const std::size_t available = maximum_body_bytes - output.size();

    if (available == 0) {
        return FragmentResult::PageFull;
    }

    const std::size_t remaining = record.size() - cursor.offset;
    const std::size_t count = std::min(available, remaining);
    output.append(record.data() + cursor.offset, count);

    if (count != remaining) {
        cursor.offset += static_cast<std::uint32_t>(count);
        return FragmentResult::PageFull;
    }

    ++cursor.index;
    cursor.offset = 0;
    return FragmentResult::Complete;
}

std::string meta_record(
    const Board& board,
    const GlyphLayer& glyphs
) {
    std::string record = "META";
    append_field(record, board.cards.size());
    append_field(record, board.live_cards);
    append_field(record, board.edges.size());
    append_field(record, board.live_edges);
    append_field(record, glyphs.cells.size());
    record.push_back('\n');
    return record;
}

bool card_record(
    CardId id,
    const Card& card,
    const CardSpatial& spatial,
    const CardFormats& formats,
    std::string& record
) {
    if (
        id >= spatial.slots.size() ||
        !spatial.slots[id].alive ||
        card.static_format >= formats.size()
    ) {
        return false;
    }

    const Rect rect = spatial.slots[id].rect;
    const i64 width = rect.right - rect.left;
    const i64 height = rect.bottom - rect.top;

    if (
        rect.left != card.pos.x ||
        rect.top != card.pos.y ||
        width <= 0 ||
        height <= 0 ||
        width > std::numeric_limits<i32>::max() ||
        height > std::numeric_limits<i32>::max()
    ) {
        return false;
    }

    std::string payload;
    StringAppendOutputStream payload_output(payload);

    if (
        !whiteboard::io::write_exchange_card_content(
            payload_output,
            card
        ) ||
        !payload_output
    ) {
        return false;
    }

    record.clear();
    record.append("CARD ");
    append_decimal(record, id);
    record.push_back(' ');

    if (!append_word(record, formats[card.static_format].name)) {
        return false;
    }

    append_field(record, card.pos.x);
    append_field(record, card.pos.y);
    append_field(record, width);
    append_field(record, height);
    append_field(record, payload.size());
    record.push_back('\n');
    record.append(payload);
    record.push_back('\n');
    return true;
}

std::string edge_record(EdgeId id, const Edge& edge) {
    std::string record = "EDGE ";
    append_decimal(record, id);
    append_field(record, edge.source.card);
    append_field(record, static_cast<u8>(edge.source.side));
    append_field(record, edge.target.card);
    append_field(record, static_cast<u8>(edge.target.side));
    append_field(record, static_cast<u8>(edge.mode));
    append_field(record, static_cast<u8>(edge.state));
    append_field(record, edge.route_bounds.left);
    append_field(record, edge.route_bounds.top);
    append_field(record, edge.route_bounds.right);
    append_field(record, edge.route_bounds.bottom);
    append_field(record, edge.points.size());

    for (const Pos point : edge.points) {
        append_field(record, point.x);
        append_field(record, point.y);
    }

    record.push_back('\n');
    return record;
}

std::vector<GlyphCell> sorted_glyphs(const GlyphLayer& glyphs) {
    std::vector<GlyphCell> result;
    result.reserve(glyphs.cells.size());

    for (const auto& [position, glyph] : glyphs.cells) {
        result.push_back({position, glyph});
    }

    std::sort(
        result.begin(),
        result.end(),
        [](const GlyphCell& left, const GlyphCell& right) {
            return
                left.pos.y < right.pos.y ||
                (left.pos.y == right.pos.y &&
                 left.pos.x < right.pos.x);
        }
    );
    return result;
}

std::string glyph_record(const GlyphCell& glyph) {
    std::string record = "GLYPH ";
    append_decimal(record, glyph.pos.x);
    append_field(record, glyph.pos.y);
    append_field(record, static_cast<std::uint32_t>(glyph.glyph));
    record.push_back('\n');
    return record;
}

} // namespace

CanonicalSnapshotResult make_canonical_snapshot_page(
    const Board& board,
    const CardSpatial& spatial,
    const GlyphLayer& glyphs,
    const CardFormats& formats,
    CanonicalSnapshotCursor cursor,
    std::size_t maximum_body_bytes,
    CanonicalSnapshotPage& page
) {
    page = {};
    const std::vector<GlyphCell> ordered_glyphs = sorted_glyphs(glyphs);
    RecordCursor card_cursor;
    RecordCursor edge_cursor;
    RecordCursor glyph_cursor;

    if (
        !decode_cursor(cursor.card, board.cards.size(), card_cursor) ||
        !decode_cursor(cursor.edge, board.edges.size(), edge_cursor) ||
        !decode_cursor(cursor.glyph, ordered_glyphs.size(), glyph_cursor) ||
        !valid_cursor_phases(
            board,
            card_cursor,
            edge_cursor,
            glyph_cursor
        )
    ) {
        return CanonicalSnapshotResult::InvalidCursor;
    }

    const bool initial = cursor == CanonicalSnapshotCursor{};

    if (initial) {
        std::string record = meta_record(board, glyphs);

        if (
            record.size() > maximum_body_bytes ||
            (record.size() == maximum_body_bytes &&
             (board.live_cards != 0 ||
              board.live_edges != 0 ||
              !ordered_glyphs.empty()))
        ) {
            return CanonicalSnapshotResult::RecordTooLarge;
        }

        page.body = std::move(record);
    }

    std::string record;

    while (card_cursor.index < board.cards.size()) {
        const CardId id = static_cast<CardId>(card_cursor.index);
        const Card* card = board.find(id);

        if (card == nullptr) {
            if (card_cursor.offset != 0) {
                return CanonicalSnapshotResult::InvalidCursor;
            }
            ++card_cursor.index;
            continue;
        }

        if (!card_record(id, *card, spatial, formats, record)) {
            return CanonicalSnapshotResult::InvalidDocument;
        }

        const FragmentResult fragment = append_fragment(
            page.body,
            record,
            maximum_body_bytes,
            card_cursor
        );

        if (fragment == FragmentResult::InvalidCursor) {
            return CanonicalSnapshotResult::InvalidCursor;
        }
        if (fragment == FragmentResult::RecordTooLarge) {
            return CanonicalSnapshotResult::RecordTooLarge;
        }
        if (fragment == FragmentResult::PageFull) {
            page.next = {
                encode_cursor(card_cursor),
                encode_cursor(edge_cursor),
                encode_cursor(glyph_cursor),
            };
            return CanonicalSnapshotResult::Success;
        }
    }

    while (edge_cursor.index < board.edges.size()) {
        const EdgeId id = static_cast<EdgeId>(edge_cursor.index);
        const Edge* edge = board.find_edge(id);

        if (edge == nullptr) {
            if (edge_cursor.offset != 0) {
                return CanonicalSnapshotResult::InvalidCursor;
            }
            ++edge_cursor.index;
            continue;
        }

        record = edge_record(id, *edge);
        const FragmentResult fragment = append_fragment(
            page.body,
            record,
            maximum_body_bytes,
            edge_cursor
        );

        if (fragment == FragmentResult::InvalidCursor) {
            return CanonicalSnapshotResult::InvalidCursor;
        }
        if (fragment == FragmentResult::RecordTooLarge) {
            return CanonicalSnapshotResult::RecordTooLarge;
        }
        if (fragment == FragmentResult::PageFull) {
            page.next = {
                encode_cursor(card_cursor),
                encode_cursor(edge_cursor),
                encode_cursor(glyph_cursor),
            };
            return CanonicalSnapshotResult::Success;
        }
    }

    while (glyph_cursor.index < ordered_glyphs.size()) {
        record = glyph_record(
            ordered_glyphs[glyph_cursor.index]
        );
        const FragmentResult fragment = append_fragment(
            page.body,
            record,
            maximum_body_bytes,
            glyph_cursor
        );

        if (fragment == FragmentResult::InvalidCursor) {
            return CanonicalSnapshotResult::InvalidCursor;
        }
        if (fragment == FragmentResult::RecordTooLarge) {
            return CanonicalSnapshotResult::RecordTooLarge;
        }
        if (fragment == FragmentResult::PageFull) {
            page.next = {
                encode_cursor(card_cursor),
                encode_cursor(edge_cursor),
                encode_cursor(glyph_cursor),
            };
            return CanonicalSnapshotResult::Success;
        }
    }

    page.next = {
        encode_cursor(card_cursor),
        encode_cursor(edge_cursor),
        encode_cursor(glyph_cursor),
    };
    page.done = true;
    return CanonicalSnapshotResult::Success;
}

bool write_canonical_snapshot(
    std::ostream& output,
    const Board& board,
    const CardSpatial& spatial,
    const GlyphLayer& glyphs,
    const CardFormats& formats
) {
    output.write(
        kCanonicalSnapshotMagic,
        sizeof(kCanonicalSnapshotMagic) - 1
    );

    CanonicalSnapshotCursor cursor;

    for (;;) {
        CanonicalSnapshotPage page;
        const CanonicalSnapshotResult result =
            make_canonical_snapshot_page(
                board,
                spatial,
                glyphs,
                formats,
                cursor,
                1024 * 1024,
                page
            );

        if (
            result != CanonicalSnapshotResult::Success ||
            (!page.done && page.next == cursor)
        ) {
            return false;
        }

        output.write(
            page.body.data(),
            static_cast<std::streamsize>(page.body.size())
        );

        if (!output) {
            return false;
        }

        if (page.done) {
            break;
        }

        cursor = page.next;
    }

    output.write("END\n", 4);
    return static_cast<bool>(output);
}

} // namespace whiteboard::verification
