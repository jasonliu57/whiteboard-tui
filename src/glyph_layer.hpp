#pragma once

#include "text/utf8.hpp"
#include "types.hpp"

#include <absl/container/flat_hash_map.h>

#include <cstddef>
#include <limits>
#include <vector>

struct GlyphCell {
    Pos pos{};
    char32_t glyph = U' ';
};

struct GlyphClipboard {
    std::vector<GlyphCell> cells;
};

using GlyphMap = absl::flat_hash_map<Pos, char32_t, PosHash>;

static bool stored_glyph(char32_t glyph) {
    const int width = rune_cell_width(glyph);
    return
        glyph != U' ' &&
        !unicode_mark(glyph) &&
        (width == 1 || width == 2);
}

static i32 glyph_width(char32_t glyph) {
    return rune_cell_width(glyph);
}

static bool valid_glyph_position(Pos pos, i32 width) {
    Rect bounds;
    return checked_rect_at(pos, {width, 1}, bounds);
}

static bool translate_glyph_position(
    Pos position,
    Pos delta,
    Pos& result
) {
    return checked_translate(position, delta, result);
}

static Rect glyph_bounds(Pos pos, char32_t glyph) {
    return rect_at(pos, {glyph_width(glyph), 1});
}

static bool glyph_overlaps(
    Pos pos,
    char32_t glyph,
    Rect selection
) {
    return overlaps(glyph_bounds(pos, glyph), selection);
}

struct GlyphLayer {
    GlyphMap cells;
    std::vector<GlyphCell> move_buffer;

    void reserve(std::size_t additional) {
        cells.reserve(cells.size() + additional);
    }

    GlyphMap::const_iterator anchor_at(Pos pos) const {
        const auto direct = cells.find(pos);

        if (direct != cells.end()) {
            return direct;
        }

        if (pos.x == std::numeric_limits<i64>::min()) {
            return cells.end();
        }

        const auto left = cells.find({pos.x - 1, pos.y});

        return
            left != cells.end() && glyph_width(left->second) == 2
                ? left
                : cells.end();
    }

    bool insert(Pos pos, char32_t glyph) {
        if (!stored_glyph(glyph)) {
            return false;
        }

        const i32 width = glyph_width(glyph);

        if (!valid_glyph_position(pos, width)) {
            return false;
        }

        for (i32 x = 0; x < width; ++x) {
            if (anchor_at({pos.x + x, pos.y}) != cells.end()) {
                return false;
            }
        }

        cells.emplace(pos, glyph);
        return true;
    }

    bool write(Pos pos, char32_t glyph) {
        GlyphCell replaced[2];
        u8 replaced_count = 0;

        if (glyph == U' ') {
            append_covering(pos, replaced, replaced_count);

            if (replaced_count == 0) {
                return false;
            }

        } else {
            if (!stored_glyph(glyph)) {
                return false;
            }

            const i32 width = glyph_width(glyph);

            if (!valid_glyph_position(pos, width)) {
                return false;
            }

            for (i32 x = 0; x < width; ++x) {
                append_covering(
                    {pos.x + x, pos.y},
                    replaced,
                    replaced_count
                );
            }

            if (
                replaced_count == 1 &&
                replaced[0].pos == pos &&
                replaced[0].glyph == glyph
            ) {
                return false;
            }

        }

        for (u8 i = 0; i < replaced_count; ++i) {
            cells.erase(replaced[i].pos);
        }

        if (glyph != U' ') {
            cells.emplace(pos, glyph);
        }

        return true;
    }

    bool write_many(const std::vector<GlyphCell>& writes) {
        if (!valid_writes(writes)) {
            return false;
        }

        reserve(writes.size());
        bool changed = false;

        for (const GlyphCell& cell : writes) {
            changed = write(cell.pos, cell.glyph) || changed;
        }

        return changed;
    }

    bool valid_writes(
        const std::vector<GlyphCell>& writes
    ) const noexcept {
        for (const GlyphCell& cell : writes) {
            if (
                cell.glyph != U' ' &&
                (!stored_glyph(cell.glyph) ||
                 !valid_glyph_position(
                    cell.pos,
                    glyph_width(cell.glyph)
                 ))
            ) {
                return false;
            }
        }

        return true;
    }

    bool collect(
        Rect selection,
        std::vector<GlyphCell>& result
    ) const {
        result.clear();

        for (const auto& [pos, glyph] : cells) {
            if (glyph_overlaps(pos, glyph, selection)) {
                result.push_back({pos, glyph});
            }
        }

        return !result.empty();
    }

    void erase_collected(const std::vector<GlyphCell>& selected) {
        for (const GlyphCell& cell : selected) {
            cells.erase(cell.pos);
        }
    }

    bool erase(Rect selection) {
        if (!collect(selection, move_buffer)) {
            return false;
        }

        erase_collected(move_buffer);
        return true;
    }

    bool place(
        const std::vector<GlyphCell>& selected,
        Pos delta
    ) {
        if (delta.x == 0 && delta.y == 0) {
            return false;
        }

        return overwrite(selected, delta, true);
    }

    bool move(Rect selection, Pos delta) {
        return
            collect(selection, move_buffer) &&
            place(move_buffer, delta);
    }

    bool paste(const GlyphClipboard& clipboard, Pos origin) {
        return overwrite(clipboard.cells, origin, false);
    }

private:
    bool overwrite(
        const std::vector<GlyphCell>& incoming,
        Pos delta,
        bool erase_source
    ) {
        if (incoming.empty()) {
            return false;
        }

        for (const GlyphCell& cell : incoming) {
            Pos destination;

            if (
                !translate_glyph_position(cell.pos, delta, destination) ||
                !valid_glyph_position(
                    destination,
                    glyph_width(cell.glyph)
                )
            ) {
                return false;
            }
        }

        if (!erase_source) {
            reserve(incoming.size());
        }

        if (erase_source) {
            erase_collected(incoming);
        }

        for (const GlyphCell& cell : incoming) {
            Pos destination;
            translate_glyph_position(cell.pos, delta, destination);
            const i32 width = glyph_width(cell.glyph);
            GlyphCell replaced[2];
            u8 replaced_count = 0;

            for (i32 x = 0; x < width; ++x) {
                append_covering(
                    {destination.x + x, destination.y},
                    replaced,
                    replaced_count
                );
            }

            for (u8 i = 0; i < replaced_count; ++i) {
                cells.erase(replaced[i].pos);
            }

            cells.emplace(destination, cell.glyph);
        }

        return true;
    }

    void append_covering(
        Pos pos,
        GlyphCell (&result)[2],
        u8& count
    ) const {
        const auto found = anchor_at(pos);

        if (found == cells.end()) {
            return;
        }

        for (u8 i = 0; i < count; ++i) {
            if (result[i].pos == found->first) {
                return;
            }
        }

        result[count++] = {found->first, found->second};
    }

};
