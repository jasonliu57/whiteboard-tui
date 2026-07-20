#include "board.hpp"

#include "../formats/draw.hpp"

#include <algorithm>

static void draw_edge_segment(
    Screen& screen,
    const EdgeSegmentRef& segment,
    const Viewport& view,
    Rect visible,
    Style style
) {
    if (segment.from.y == segment.to.y) {
        const i64 full_left = std::min(segment.from.x, segment.to.x);
        const i64 full_right = std::max(segment.from.x, segment.to.x);
        const i64 left = std::max(full_left, visible.left);
        const i64 right = std::min(full_right, visible.right - 1);

        for (i64 x = left; x <= right; ++x) {
            u8 mask = 0;

            if (x > full_left) {
                mask |= EdgeWest;
            }

            if (x < full_right) {
                mask |= EdgeEast;
            }

            screen.stroke_edge(
                static_cast<i32>(x - view.x),
                static_cast<i32>(segment.from.y - view.y),
                mask,
                segment.edge,
                segment.segment,
                style
            );
        }
        return;
    }

    const i64 full_top = std::min(segment.from.y, segment.to.y);
    const i64 full_bottom = std::max(segment.from.y, segment.to.y);
    const i64 top = std::max(full_top, visible.top);
    const i64 bottom = std::min(full_bottom, visible.bottom - 1);

    for (i64 y = top; y <= bottom; ++y) {
        u8 mask = 0;

        if (y > full_top) {
            mask |= EdgeNorth;
        }

        if (y < full_bottom) {
            mask |= EdgeSouth;
        }

        screen.stroke_edge(
            static_cast<i32>(segment.from.x - view.x),
            static_cast<i32>(y - view.y),
            mask,
            segment.edge,
            segment.segment,
            style
        );
    }
}

void render_board_span(
    Screen& screen,
    const Board& board,
    const CardSpatial& spatial,
    const EdgeSpatial& edge_spatial,
    const GlyphLayer& glyphs,
    const Viewport& view,
    Rect visible,
    const CardFormats& formats,
    const CardSession& session,
    CardId hovered,
    CardId selected,
    EdgeId selected_edge,
    const EdgePoints* edge_preview,
    bool edge_preview_valid,
    const Rect* hidden_glyphs,
    std::span<const GlyphCell> glyph_preview,
    Pos glyph_preview_delta
) {
    screen.clear();

    edge_spatial.query(visible, [&](const EdgeSegmentRef& segment) {
        if (segment.edge == selected_edge) {
            return true;
        }

        const Edge& edge = board.get_edge(segment.edge);
        const Style style = edge.state == RouteState::Ready
            ? Style{6, 0, AttrNone}
            : Style{1, 0, AttrBold};
        draw_edge_segment(screen, segment, view, visible, style);
        return true;
    });

    if (
        selected_edge != kNoEdge &&
        selected_edge < edge_spatial.slot_count
    ) {
        const Edge& edge = board.get_edge(selected_edge);

        for (u32 i = 0; i + 1 < edge.points.size(); ++i) {
            draw_edge_segment(
                screen,
                EdgeSegmentRef{
                    .edge = selected_edge,
                    .segment = i,
                    .from = edge.points[i],
                    .to = edge.points[i + 1],
                },
                view,
                visible,
                Style{14, 0, AttrBold}
            );
        }
    }

    if (edge_preview != nullptr) {
        const Style style = edge_preview_valid
            ? Style{10, 0, AttrBold}
            : Style{9, 0, AttrBold};

        for (u32 i = 0; i + 1 < edge_preview->size(); ++i) {
            const Pos first = (*edge_preview)[i];
            const Pos second = (*edge_preview)[i + 1];

            draw_edge_segment(
                screen,
                EdgeSegmentRef{
                    .edge = kNoEdge,
                    .segment = i,
                    .from = first,
                    .to = second,
                },
                view,
                visible,
                style
            );
        }
    }

    if (!glyphs.cells.empty()) {
        const std::size_t viewport_cells =
            static_cast<std::size_t>(screen.width()) *
            static_cast<std::size_t>(screen.height());

        if (glyphs.cells.size() < viewport_cells) {
            for (const auto& [position, glyph] : glyphs.cells) {
                if (
                    position.x < visible.left ||
                    position.x >= visible.right ||
                    position.y < visible.top ||
                    position.y >= visible.bottom
                ) {
                    continue;
                }

                if (
                    hidden_glyphs != nullptr &&
                    glyph_overlaps(position, glyph, *hidden_glyphs)
                ) {
                    continue;
                }

                screen.paint_layer(
                    static_cast<i32>(position.x - view.x),
                    static_cast<i32>(position.y - view.y),
                    display_rune(glyph),
                    Style{7, 0, AttrNone},
                    kNoCard,
                    PaintLayer::Glyph
                );
            }
        } else {
            for (i64 y = visible.top; y < visible.bottom; ++y) {
                for (i64 x = visible.left; x < visible.right; ++x) {
                    const auto cell = glyphs.cells.find({x, y});

                    if (cell == glyphs.cells.end()) {
                        continue;
                    }

                    if (
                        hidden_glyphs != nullptr &&
                        glyph_overlaps(
                            cell->first,
                            cell->second,
                            *hidden_glyphs
                        )
                    ) {
                        continue;
                    }

                    screen.paint_layer(
                        static_cast<i32>(x - view.x),
                        static_cast<i32>(y - view.y),
                        display_rune(cell->second),
                        Style{7, 0, AttrNone},
                        kNoCard,
                        PaintLayer::Glyph
                    );
                }
            }
        }
    }

    for (const GlyphCell& cell : glyph_preview) {
        Pos position;

        if (
            !translate_glyph_position(
                cell.pos,
                glyph_preview_delta,
                position
            ) ||
            !valid_glyph_position(
                position,
                glyph_width(cell.glyph)
            ) ||
            !overlaps(glyph_bounds(position, cell.glyph), visible)
        ) {
            continue;
        }

        screen.paint_layer(
            static_cast<i32>(position.x - view.x),
            static_cast<i32>(position.y - view.y),
            display_rune(cell.glyph),
            Style{10, 0, AttrBold},
            kNoCard,
            PaintLayer::Glyph
        );
    }

    spatial.query(visible, [&](CardId id) {
        const Card& card = board.get(id);
        const CardFormat& format = formats[card.static_format];

        const i32 screen_x = static_cast<i32>(card.pos.x - view.x);
        const i32 screen_y = static_cast<i32>(card.pos.y - view.y);
        const FormatSession* active =
            session.active == id ? &session.state : nullptr;
        CardVisualState visual_state = CardVisualState::Normal;

        if (active != nullptr) {
            visual_state = CardVisualState::Editing;
        } else if (selected == id) {
            visual_state = CardVisualState::Selected;
        } else if (hovered == id) {
            visual_state = CardVisualState::Hover;
        }

        format.draw(
            screen,
            card.data,
            id,
            screen_x,
            screen_y,
            format,
            visual_state,
            active
        );
        return true;
    });

    const CardId focused =
        session.active == kNoCard ? selected : session.active;

    if (
        focused == kNoCard ||
        focused >= board.cards.size() ||
        !board.cards[focused].has_value()
    ) {
        return;
    }

    const Card& card = board.get(focused);
    const CardFormat& format = formats[card.static_format];
    const Rect rect = spatial.slots[focused].rect;
    const Extent extent{
        static_cast<i32>(rect.right - rect.left),
        static_cast<i32>(rect.bottom - rect.top),
    };

    if (!overlaps(rect, visible) || format.borderless) {
        return;
    }

    draw_box_outline(
        screen,
        extent,
        focused,
        static_cast<i32>(card.pos.x - view.x),
        static_cast<i32>(card.pos.y - view.y),
        format,
        session.active == focused
            ? CardVisualState::Editing
            : CardVisualState::Selected,
        PaintLayer::Overlay
    );
}

void render_board(
    Screen& screen,
    const Board& board,
    const CardSpatial& spatial,
    const EdgeSpatial& edge_spatial,
    const GlyphLayer& glyphs,
    const Viewport& view,
    Rect visible,
    const CardFormats& formats,
    const CardSession& session,
    CardId hovered,
    CardId selected,
    EdgeId selected_edge,
    const EdgePoints* edge_preview,
    bool edge_preview_valid,
    const Rect* hidden_glyphs,
    const std::vector<GlyphCell>* glyph_preview,
    Pos glyph_preview_delta
) {
    render_board_span(
        screen,
        board,
        spatial,
        edge_spatial,
        glyphs,
        view,
        visible,
        formats,
        session,
        hovered,
        selected,
        selected_edge,
        edge_preview,
        edge_preview_valid,
        hidden_glyphs,
        glyph_preview == nullptr
            ? std::span<const GlyphCell>{}
            : std::span<const GlyphCell>{*glyph_preview},
        glyph_preview_delta
    );
}

void draw_world_outline(
    Screen& screen,
    Rect rect,
    const Viewport& view,
    Rect visible,
    char32_t glyph,
    Style style
) {
    const i64 left = std::max(rect.left, visible.left);
    const i64 right = std::min(rect.right, visible.right);
    const i64 top = std::max(rect.top, visible.top);
    const i64 bottom = std::min(rect.bottom, visible.bottom);

    if (left >= right || top >= bottom) {
        return;
    }

    const DisplayRune display = display_rune(glyph);
    const auto paint = [&](i64 x, i64 y) {
        screen.paint_layer(
            static_cast<i32>(x - view.x),
            static_cast<i32>(y - view.y),
            display,
            style,
            kNoCard,
            PaintLayer::Spatial
        );
    };

    if (rect.top >= visible.top && rect.top < visible.bottom) {
        for (i64 x = left; x < right; ++x) {
            paint(x, rect.top);
        }
    }

    const i64 last_y = rect.bottom - 1;

    if (
        last_y != rect.top &&
        last_y >= visible.top &&
        last_y < visible.bottom
    ) {
        for (i64 x = left; x < right; ++x) {
            paint(x, last_y);
        }
    }

    if (rect.left >= visible.left && rect.left < visible.right) {
        for (i64 y = top; y < bottom; ++y) {
            paint(rect.left, y);
        }
    }

    const i64 last_x = rect.right - 1;

    if (
        last_x != rect.left &&
        last_x >= visible.left &&
        last_x < visible.right
    ) {
        for (i64 y = top; y < bottom; ++y) {
            paint(last_x, y);
        }
    }
}
