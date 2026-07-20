#include "overview.hpp"

#include <bit>
#include <cmath>
#include <stdexcept>

bool board_overview_bounds(const Board& board, const CardSpatial& spatial,
                           Rect& bounds, const GlyphLayer* glyphs) {
    bool found = false;
    const auto include = [&](Rect rect) {
        bounds = found ? unite(bounds, rect) : rect;
        found = true;
    };
    bounds = {};
    for (CardId id = 0; id < board.cards.size(); ++id) {
        if (board.find(id)) include(spatial.slots[id].rect);
    }
    for (EdgeId id = 0; id < board.edges.size(); ++id) {
        const Edge* edge = board.find_edge(id);
        if (!edge || !board.find(edge->source.card) || !board.find(edge->target.card)) continue;
        for (Pos point : edge->points) include(point_rect(point));
    }
    if (glyphs) {
        for (const auto& [pos, glyph] : glyphs->cells) include(glyph_bounds(pos, glyph));
    }
    return found;
}

long double BoardProjection::distance(i64 value, i64 origin) {
    // Subtract integers before conversion, including on WASM where long double
    // has double precision. A small board near an i64 limit must not collapse.
    return value >= origin
        ? static_cast<long double>(static_cast<u64>(value) - static_cast<u64>(origin))
        : -static_cast<long double>(static_cast<u64>(origin) - static_cast<u64>(value));
}

long double BoardProjection::offset(i64 value, i64 origin) const {
    return distance(value, origin) * scale;
}
i32 BoardProjection::floor(i64 value, i64 origin) const {
    return margin + static_cast<i32>(std::floor(offset(value, origin)));
}
i32 BoardProjection::ceil(i64 value, i64 origin) const {
    return margin + static_cast<i32>(std::ceil(offset(value, origin)));
}
i32 BoardProjection::point(i64 value, i64 origin) const {
    return margin + static_cast<i32>(std::llround(offset(value, origin)));
}
double BoardProjection::x(i64 value) const {
    return static_cast<double>(distance(value, bounds.left) / distance(bounds.right, bounds.left));
}
double BoardProjection::y(i64 value) const {
    return static_cast<double>(distance(value, bounds.top) / distance(bounds.bottom, bounds.top));
}

Pos BoardProjection::world(double x, double y) const {
    if (!valid_rect(bounds) || !std::isfinite(x) || !std::isfinite(y) ||
        x < 0 || x > 1 || y < 0 || y > 1) throw std::runtime_error("invalid overview position");
    const auto axis = [](double value, i64 first, i64 last) {
        const u64 span = static_cast<u64>(last) - static_cast<u64>(first);
        const long double rounded = std::floor(static_cast<long double>(value) * span + 0.5L);
        // Clamp before converting: floating point can round UINT64_MAX to 2^64.
        if (rounded >= static_cast<long double>(span - 1)) return last - 1;
        const u64 bits = static_cast<u64>(first) + static_cast<u64>(rounded);
        return std::bit_cast<i64>(bits);
    };
    return {axis(x, bounds.left, bounds.right), axis(y, bounds.top, bounds.bottom)};
}
