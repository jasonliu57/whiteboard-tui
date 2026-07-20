#pragma once

#include "../types.hpp"

#include <algorithm>
#include <cstddef>
#include <limits>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

enum class PaintLayer : u8 {
    Edge,
    Glyph,
    Card,
    Overlay,
    Spatial,
};

struct PaintOrder {
    PaintLayer layer = PaintLayer::Edge;
    u32 id = 0;
};

static bool paint_below(PaintOrder first, PaintOrder second) {
    if (first.layer != second.layer) {
        return first.layer < second.layer;
    }

    return first.id < second.id;
}

enum EdgeDirection : u8 {
    EdgeNorth = 1 << 0,
    EdgeEast  = 1 << 1,
    EdgeSouth = 1 << 2,
    EdgeWest  = 1 << 3,
};

static char32_t edge_glyph(u8 mask) {
    switch (mask) {
        case EdgeNorth:
        case EdgeSouth:
        case EdgeNorth | EdgeSouth:
            return U'│';

        case EdgeEast:
        case EdgeWest:
        case EdgeEast | EdgeWest:
            return U'─';

        case EdgeNorth | EdgeEast: return U'└';
        case EdgeNorth | EdgeWest: return U'┘';
        case EdgeSouth | EdgeEast: return U'┌';
        case EdgeSouth | EdgeWest: return U'┐';
        case EdgeNorth | EdgeEast | EdgeSouth: return U'├';
        case EdgeNorth | EdgeSouth | EdgeWest: return U'┤';
        case EdgeEast | EdgeSouth | EdgeWest: return U'┬';
        case EdgeNorth | EdgeEast | EdgeWest: return U'┴';
        default: return U'┼';
    }
}

constexpr u32 kNoEdgeStroke = ~u32{0};

struct EdgeStroke {
    EdgeId edge = kNoEdge;
    u32 segment = 0;
    u8 mask = 0;
    u32 next = kNoEdgeStroke;
};

struct ScreenCell {
    std::u32string combining;
    PaintOrder order{};
    char32_t glyph = U' ';
    Style style{};
    CardId owner = kNoCard;
    u32 first_edge = kNoEdgeStroke;

    // 共用文字格式的 selection 對應；其他格式可忽略。
    u32 text_row = ~u32{0};
    u32 text_byte = ~u32{0};
    u8 edge_mask = 0;

    // 0 是雙寬字元 continuation。
    u8 width = 1;

    void reset() noexcept {
        glyph = U' ';
        combining.clear();
        style = {};
        owner = kNoCard;
        order = {};
        edge_mask = 0;
        first_edge = kNoEdgeStroke;
        width = 1;
        text_row = ~u32{0};
        text_byte = ~u32{0};
    }
};

class Screen {
public:
    Screen(i32 width, i32 height)
        : width_(width),
          height_(height),
          cells_(cell_count(width, height)) {}

    i32 width() const noexcept {
        return width_;
    }

    i32 height() const noexcept {
        return height_;
    }

    ScreenCell& at(i32 x, i32 y) {
        return cells_[static_cast<std::size_t>(y) * width_ + x];
    }

    const ScreenCell& at(i32 x, i32 y) const {
        return cells_[static_cast<std::size_t>(y) * width_ + x];
    }

    void resize(i32 width, i32 height) {
        std::vector<ScreenCell> replacement(cell_count(width, height));
        width_ = width;
        height_ = height;
        cells_ = std::move(replacement);
        edge_strokes_.clear();
    }

    void clear() {
        for (ScreenCell& cell : cells_) {
            cell.reset();
        }
        edge_strokes_.clear();
    }

    void paint(
        i32 x,
        i32 y,
        DisplayRune rune,
        Style style,
        CardId owner,
        u32 row = ~u32{0},
        u32 byte = ~u32{0}
    ) {
        paint_layer(
            x,
            y,
            rune,
            style,
            owner,
            PaintLayer::Card,
            row,
            byte
        );
    }

    void paint_layer(
        i32 x,
        i32 y,
        DisplayRune rune,
        Style style,
        CardId owner,
        PaintLayer layer,
        u32 row = ~u32{0},
        u32 byte = ~u32{0}
    ) {
        if (rune.width == 0) {
            paint_combining(
                x,
                y,
                rune.glyph,
                owner,
                {layer, owner == kNoCard ? 0 : owner},
                row,
                byte
            );
            return;
        }

        if (
            (rune.width != 1 && rune.width != 2) ||
            y < 0 || y >= height_ ||
            x < 0 || x >= width_ ||
            rune.width > width_ - x
        ) {
            return;
        }

        const PaintOrder order{
            .layer = layer,
            .id = owner == kNoCard ? 0 : owner,
        };

        if (paint_below(order, glyph_order(x, y))) {
            return;
        }

        if (
            rune.width == 2 &&
            paint_below(order, glyph_order(x + 1, y))
        ) {
            return;
        }

        erase_glyph_neighbors(x, y);

        if (rune.width == 2) {
            erase_glyph_neighbors(x + 1, y);
        }

        ScreenCell& lead = at(x, y);
        set_cell(
            lead,
            rune.glyph,
            style,
            owner,
            order,
            static_cast<u8>(rune.width),
            row,
            byte
        );

        if (rune.width == 2) {
            ScreenCell& continuation = at(x + 1, y);
            set_cell(
                continuation,
                U'\0',
                style,
                owner,
                order,
                0,
                row,
                byte
            );
        }
    }

    void fill(
        i32 x,
        i32 y,
        i32 width,
        i32 height,
        Style style,
        CardId owner
    ) {
        const i32 left = static_cast<i32>(std::max<i64>(0, x));
        const i32 top = static_cast<i32>(std::max<i64>(0, y));
        const i32 right = static_cast<i32>(std::min<i64>(
            width_,
            static_cast<i64>(x) + width
        ));
        const i32 bottom = static_cast<i32>(std::min<i64>(
            height_,
            static_cast<i64>(y) + height
        ));
        const PaintOrder order{
            .layer = PaintLayer::Card,
            .id = owner == kNoCard ? 0 : owner,
        };

        for (i32 screen_y = top; screen_y < bottom; ++screen_y) {
            for (i32 screen_x = left; screen_x < right; ++screen_x) {
                if (paint_below(order, glyph_order(screen_x, screen_y))) {
                    continue;
                }

                erase_glyph_neighbors(screen_x, screen_y);
                set_cell(
                    at(screen_x, screen_y),
                    U' ',
                    style,
                    owner,
                    order,
                    1,
                    ~u32{0},
                    ~u32{0}
                );
            }
        }
    }

    void stroke_edge(
        i32 x,
        i32 y,
        u8 mask,
        EdgeId edge,
        u32 segment,
        Style style
    ) {
        if (x < 0 || x >= width_ || y < 0 || y >= height_) {
            return;
        }

        ScreenCell& cell = at(x, y);
        const u32 stroke = static_cast<u32>(edge_strokes_.size());
        edge_strokes_.push_back({
            .edge = edge,
            .segment = segment,
            .mask = mask,
            .next = cell.first_edge,
        });

        cell.edge_mask |= mask;
        cell.first_edge = stroke;
        cell.glyph = edge_glyph(cell.edge_mask);
        cell.style = style;
        cell.owner = kNoCard;
        cell.order = {PaintLayer::Edge, 0};
        cell.width = 1;
        cell.text_row = ~u32{0};
        cell.text_byte = ~u32{0};
    }

    void invert(i32 x, i32 y) {
        if (x < 0 || x >= width_ || y < 0 || y >= height_) {
            return;
        }

        i32 lead_x = x;

        if (at(x, y).width == 0) {
            lead_x = x - 1;
        }

        ScreenCell& lead = at(lead_x, y);
        std::swap(lead.style.foreground, lead.style.background);

        if (lead.width == 2) {
            ScreenCell& continuation = at(lead_x + 1, y);
            std::swap(
                continuation.style.foreground,
                continuation.style.background
            );
        }
    }

    void invert_span(
        i32 x,
        i32 y,
        i32 width,
        CardId owner
    ) {
        if (y < 0 || y >= height_ || width <= 0) {
            return;
        }

        const i32 left = std::max(0, x);
        const i32 right = static_cast<i32>(std::min<i64>(
            width_,
            static_cast<i64>(x) + width
        ));

        for (i32 screen_x = left; screen_x < right; ++screen_x) {
            const ScreenCell& cell = at(screen_x, y);

            if (
                cell.width != 0 &&
                (owner == kNoCard || cell.owner == owner)
            ) {
                invert(screen_x, y);
            }
        }
    }

    template<class Visit>
    void visit_edge_strokes(i32 x, i32 y, Visit&& visit) const {
        if (x < 0 || x >= width_ || y < 0 || y >= height_) {
            return;
        }

        u32 stroke = at(x, y).first_edge;

        while (stroke != kNoEdgeStroke) {
            const EdgeStroke& value = edge_strokes_[stroke];
            visit(value);
            stroke = value.next;
        }
    }

private:
    static std::size_t cell_count(i32 width, i32 height) {
        if (width < 0 || height < 0) {
            throw std::invalid_argument{"negative screen extent"};
        }

        const std::size_t columns = static_cast<std::size_t>(width);
        const std::size_t rows = static_cast<std::size_t>(height);

        if (
            rows != 0 &&
            columns > std::numeric_limits<std::size_t>::max() / rows
        ) {
            throw std::length_error{"screen extent is too large"};
        }

        return columns * rows;
    }

    i32 width_;
    i32 height_;
    std::vector<ScreenCell> cells_;
    std::vector<EdgeStroke> edge_strokes_;

    static void set_cell(
        ScreenCell& cell,
        char32_t glyph,
        Style style,
        CardId owner,
        PaintOrder order,
        u8 width,
        u32 text_row,
        u32 text_byte
    ) {
        cell.glyph = glyph;
        cell.combining.clear();
        cell.style = style;
        cell.owner = owner;
        cell.order = order;
        cell.edge_mask = 0;
        cell.first_edge = kNoEdgeStroke;
        cell.width = width;
        cell.text_row = text_row;
        cell.text_byte = text_byte;
    }

    PaintOrder glyph_order(i32 x, i32 y) const {
        const ScreenCell& cell = at(x, y);

        return cell.width == 0 && x > 0
            ? at(x - 1, y).order
            : cell.order;
    }

    void paint_combining(
        i32 x,
        i32 y,
        char32_t codepoint,
        CardId owner,
        PaintOrder order,
        u32 row,
        u32 byte
    ) {
        if (y < 0 || y >= height_ || x <= 0 || x > width_) {
            return;
        }

        i32 lead_x = x - 1;

        if (at(lead_x, y).width == 0) {
            --lead_x;
        }

        if (lead_x < 0) {
            return;
        }

        ScreenCell& lead = at(lead_x, y);

        if (
            lead.width == 0 ||
            lead.glyph == U' ' ||
            lead.owner != owner ||
            lead.order.layer != order.layer ||
            lead.order.id != order.id ||
            (row != ~u32{0} &&
             (lead.text_row != row || lead.text_byte >= byte))
        ) {
            return;
        }

        lead.combining.push_back(codepoint);
    }

    void erase_glyph_neighbors(i32 x, i32 y) {
        if (x < 0 || x >= width_) {
            return;
        }

        ScreenCell& cell = at(x, y);

        if (cell.width == 0 && x > 0) {
            at(x - 1, y).reset();
        } else if (cell.width == 2 && x + 1 < width_) {
            at(x + 1, y).reset();
        }
    }
};
