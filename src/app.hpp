#pragma once

#include "board_document.hpp"
#include "decimal.hpp"
#include "edge_route.hpp"
#include "glyph_layer.hpp"
#include "history.hpp"
#include "formats/registry.hpp"
#include "formats/validation.hpp"
#include "render/board.hpp"
#include "spatial/board_spatial.hpp"
#include "storage/api.hpp"

#include <algorithm>
#include <cstddef>
#include <optional>
#include <span>
#include <string>
#include <string_view>
#include <utility>
#include <variant>
#include <vector>

struct AppInputResult {
    bool handled = false;
    bool focus_requested = false;
    CardId focus_card = kNoCard;
};

static std::string clipboard_card_name(
    const Card& card,
    CardId id,
    std::string_view format_name
) {
    const std::string_view explicit_name = card_name(card);

    if (!explicit_name.empty()) {
        return std::string{explicit_name};
    }

    std::string name{format_name};
    name.push_back('-');
    append_decimal(name, id);

    switch (card_save_format(card)) {
        case SaveFormat::PlainText: name.append(".txt"); break;
        case SaveFormat::Markdown:  name.append(".md"); break;
        case SaveFormat::TodoText:  name.append(".todo.txt"); break;
        case SaveFormat::Csv:       name.append(".csv"); break;
        case SaveFormat::FolderTree: break;
    }

    return name;
}

static GlyphClipboard make_glyph_clipboard(
    Rect selection,
    const std::vector<GlyphCell>& selected
) {
    Pos origin{selection.left, selection.top};

    for (const GlyphCell& cell : selected) {
        origin.x = std::min(origin.x, cell.pos.x);
        origin.y = std::min(origin.y, cell.pos.y);
    }

    GlyphClipboard clipboard;
    clipboard.cells.reserve(selected.size());

    for (const GlyphCell& cell : selected) {
        clipboard.cells.push_back({
            .pos = {
                cell.pos.x - origin.x,
                cell.pos.y - origin.y,
            },
            .glyph = cell.glyph,
        });
    }

    return clipboard;
}

struct App {
    BoardDocument document;
    Board& board = document.board;
    GlyphLayer& glyphs = document.glyphs;
    CardSpatial& spatial = document.spatial;
    EdgeSpatial& edge_spatial = document.edge_spatial;
    EdgeRouter& edge_router = document.edge_router;
    History& history = document.history;
    std::vector<EdgeId>& affected_edges = document.affected_edges;
    std::vector<u32>& edge_marks = document.edge_marks;
    u32& edge_mark_generation = document.edge_mark_generation;
    bool& untracked_dirty = document.untracked_dirty;
    u64& revision = document.revision;
    CardFormats formats;
    CardSession session;
    Screen screen;
    Clipboard clipboard;
    std::string file_error;

    App(i32 screen_width, i32 screen_height)
        : formats(make_card_formats()),
          screen(screen_width, screen_height) {}

    void begin_card(CardId id) {
        session.end();
        session.active = id;

        Card& card = board.get(id);
        formats[card.static_format].begin(
            session.state,
            card.data
        );

        if (TextSession* text =
                std::get_if<TextSession>(&session.state)) {
            begin_text_syntax(
                *text,
                std::get<TextCardData>(card.data)
            );
        }
    }

    void end_card() {
        session.end();
    }

    AppInputResult handle_active_input(const InputEvent& event) {
        Card& card = board.get(session.active);
        const CardFormat& format = formats[card.static_format];
        const Rect old_rect = spatial.slots[session.active].rect;
        FormatContext context{
            card.data,
            session.state,
            clipboard,
            format.minimum_layout,
            format.maximum_layout,
        };

        FormatAction action = format.input(context, event);
        const AppInputResult result{
            action.handled,
            action.focus_requested,
            action.focus_card,
        };

        if (action.mutation != FormatMutation::Stored) {
            return result;
        }

        const bool tracked =
            !std::holds_alternative<std::monostate>(action.undo);
        std::vector<EdgeGeometryChange> edge_changes;

        if (action.layout_changed) {
            Rect new_rect;

            if (!checked_rect_at(
                    card.pos,
                    format.measure(card.data),
                    new_rect
                )) {
                if (tracked) {
                    format.swap_undo(
                        card.data,
                        &session.state,
                        action.undo
                    );
                }
                return result;
            }

            if (old_rect != new_rect) {
                spatial.change(session.active, new_rect);
                card_geometry_changed(
                    session.active,
                    old_rect,
                    new_rect,
                    tracked ? &edge_changes : nullptr
                );
            }
        }

        if (!tracked) {
            history.branch();
            untracked_dirty = true;
        } else {
            history.push(Change{FormatChange{
                .card = session.active,
                .undo = std::move(action.undo),
                .layout_changed = action.layout_changed,
                .edges = std::move(edge_changes),
            }});
        }

        ++revision;

        return result;
    }

    void resize_screen(i32 width, i32 height) {
        screen.resize(width, height);
    }

    Extent card_extent(CardId id) const {
        const Rect rect = spatial.slots[id].rect;
        return {
            static_cast<i32>(rect.right - rect.left),
            static_cast<i32>(rect.bottom - rect.top),
        };
    }

    bool has_card(CardId id) const {
        return board.find(id) != nullptr;
    }

    bool has_edge(EdgeId id) const {
        return board.find_edge(id) != nullptr;
    }

    bool card_port_at(
        CardId id,
        Pos position,
        PortSide& side
    ) const {
        const Rect rect = spatial.slots[id].rect;
        const i64 right = rect.right - 1;
        const i64 bottom = rect.bottom - 1;

        if (
            position.x < rect.left || position.x > right ||
            position.y < rect.top || position.y > bottom
        ) {
            return false;
        }

        if (position.y == rect.top) {
            side = PortSide::Top;
        } else if (position.x == right) {
            side = PortSide::Right;
        } else if (position.y == bottom) {
            side = PortSide::Bottom;
        } else if (position.x == rect.left) {
            side = PortSide::Left;
        } else {
            return false;
        }

        return true;
    }

    PortGeometry port_geometry(EdgeEnd end) const {
        return edge_port_geometry(spatial, end);
    }

    bool route_edge(Edge& edge, Rect bounds) {
        return edge_router.route(
            board,
            spatial,
            edge,
            bounds
        );
    }

    bool route_edge_leg_preview(
        RouteTerminal source,
        RouteTerminal target,
        Rect bounds,
        const EdgePoints& prefix,
        EdgePoints& points
    ) {
        return edge_router.route_leg(
            spatial,
            source,
            target,
            bounds,
            &prefix,
            points
        );
    }

    bool validate_edge_draft(
        EdgeEnd source,
        const EdgeEnd* target,
        const EdgePoints& points
    ) const {
        return
            validate_edge_geometry(points) &&
            validate_edge_collision(
                board,
                spatial,
                source,
                target,
                points
            );
    }

    bool reroute_edge(EdgeId id, Rect bounds) {
        Edge replacement = board.get_edge(id);

        if (!route_edge(replacement, bounds)) {
            return false;
        }

        replacement.mode = RouteMode::Automatic;
        replace_edge(id, std::move(replacement));
        return true;
    }

    void commit_manual_edge(EdgeId id, Edge&& replacement) {
        replace_edge(id, std::move(replacement));
    }

    bool prepare_manual_edge(Edge& replacement) const {
        replacement.mode = RouteMode::Manual;
        update_edge_ports(spatial, replacement);

        if (!validate_edge(board, spatial, replacement)) {
            return false;
        }

        replacement.state = RouteState::Ready;
        return true;
    }

    CardId card_at(Pos position) const {
        CardId result = kNoCard;

        spatial.query(point_rect(position), [&](CardId id) {
            if (result == kNoCard || id > result) {
                result = id;
            }
            return true;
        });

        return result;
    }

    std::string_view card_format_name(CardId id) const {
        return formats[board.get(id).static_format].name;
    }

    bool is_folder(CardId id) const {
        return std::holds_alternative<FolderCardData>(
            board.get(id).data
        );
    }

    CardId add_card(Card&& card) {
        Rect unused;

        if (
            board.cards.size() >= kNoCard ||
            !card_rect(card, unused)
        ) {
            return kNoCard;
        }

        CardChange change = insert_card(std::move(card));
        const CardId id = change.id;
        history.push(Change{std::move(change)});
        ++revision;
        return id;
    }

    CardId add_cards(std::vector<Card>&& cards) {
        if (
            cards.empty() ||
            cards.size() >
                static_cast<std::size_t>(kNoCard) - board.cards.size()
        ) {
            return kNoCard;
        }

        for (const Card& card : cards) {
            Rect unused;

            if (!card_rect(card, unused)) {
                return kNoCard;
            }
        }

        const CardId first = static_cast<CardId>(board.cards.size());
        CardBatchChange change;
        change.cards.reserve(cards.size());
        board.cards.reserve(board.cards.size() + cards.size());
        board.incident.reserve(board.incident.size() + cards.size());
        spatial.reserve(spatial.slots.size() + cards.size());

        for (Card& card : cards) {
            change.cards.push_back(insert_card(std::move(card)));
        }

        history.push(Change{std::move(change)});
        ++revision;
        return first;
    }

    bool replace_card(CardId id, CardData&& data) {
        const Card* existing = board.find(id);

        if (existing == nullptr) {
            return false;
        }

        const Card& card = *existing;
        const CardFormat& format = formats[card.static_format];
        Rect unused;

        if (
            !card_data_matches(format.data_kind, data) ||
            !extent_in_format(format.measure(data), format) ||
            !checked_rect_at(card.pos, format.measure(data), unused)
        ) {
            return false;
        }

        CardReplaceChange change{
            .id = id,
            .data = std::move(data),
            .edges = {},
        };
        swap_card_replace(change);
        history.push(Change{std::move(change)});
        ++revision;
        return true;
    }

    EdgeId add_edge(Edge&& edge) {
        if (
            board.edges.size() >= kNoEdge ||
            !validate_edge(board, spatial, edge)
        ) {
            return kNoEdge;
        }

        const EdgeId id = board.add_edge(std::move(edge));
        edge_spatial.insert(id, board.get_edge(id));
        history.push(Change{EdgeChange{
            .id = id,
            .edge = std::nullopt,
        }});
        ++revision;
        return id;
    }

    void erase_edge(EdgeId id) {
        if (board.find_edge(id) == nullptr) {
            return;
        }

        EdgeChange change{
            .id = id,
            .edge = std::nullopt,
        };
        swap_edge(change);
        history.push(Change{std::move(change)});
        ++revision;
    }

    bool replace_edge(EdgeId id, Edge&& replacement) {
        if (
            board.find_edge(id) == nullptr ||
            !validate_edge(board, spatial, replacement)
        ) {
            return false;
        }

        EdgeEditChange change{
            .id = id,
            .edge = std::move(replacement),
        };
        swap_edge_edit(change);
        history.push(Change{std::move(change)});
        ++revision;
        return true;
    }

    bool set_glyph(Pos pos, char32_t glyph) {
        if (!glyphs.write(pos, glyph)) {
            return false;
        }

        glyph_changed();
        return true;
    }

    bool write_glyphs(const std::vector<GlyphCell>& writes) {
        if (!glyphs.write_many(writes)) {
            return false;
        }

        glyph_changed();
        return true;
    }

    bool collect_glyphs(
        Rect selection,
        std::vector<GlyphCell>& result
    ) const {
        return glyphs.collect(selection, result);
    }

    bool place_glyphs(
        const std::vector<GlyphCell>& selected,
        Pos delta
    ) {
        if (!glyphs.place(selected, delta)) {
            return false;
        }

        glyph_changed();
        return true;
    }

    bool move_glyphs(Rect selection, Pos delta) {
        if (!glyphs.move(selection, delta)) {
            return false;
        }

        glyph_changed();
        return true;
    }

    bool erase_glyphs(Rect selection) {
        if (!glyphs.erase(selection)) {
            return false;
        }

        glyph_changed();
        return true;
    }

    CardId replace_glyphs_with_card(
        Card&& card,
        const std::vector<GlyphCell>& selected
    ) {
        const CardId id = add_card(std::move(card));

        if (id == kNoCard) {
            return kNoCard;
        }

        glyphs.erase_collected(selected);
        history.clear();
        untracked_dirty = true;
        return id;
    }

    void replace_card_with_glyphs(
        CardId id,
        Rect footprint,
        const std::vector<GlyphCell>& replacement
    ) {
        if (
            board.find(id) == nullptr ||
            !glyphs.valid_writes(replacement)
        ) {
            return;
        }

        erase_card(id);
        glyphs.erase(footprint);
        glyphs.write_many(replacement);
        history.clear();
        untracked_dirty = true;
    }

    bool copy_glyph(Pos pos) {
        const auto found = glyphs.anchor_at(pos);

        if (found == glyphs.cells.end()) {
            return false;
        }

        GlyphClipboard copy;
        copy.cells.push_back({
            .pos = {},
            .glyph = found->second,
        });
        clipboard = std::move(copy);
        return true;
    }

    bool copy_glyphs(Rect selection) {
        std::vector<GlyphCell> selected;

        if (!glyphs.collect(selection, selected)) {
            return false;
        }

        clipboard = make_glyph_clipboard(selection, selected);
        return true;
    }

    bool cut_glyphs(Rect selection) {
        std::vector<GlyphCell> selected;

        if (!glyphs.collect(selection, selected)) {
            return false;
        }

        clipboard = make_glyph_clipboard(selection, selected);
        glyphs.erase_collected(selected);
        glyph_changed();
        return true;
    }

    bool paste_glyphs(Pos origin) {
        const GlyphClipboard* copy =
            std::get_if<GlyphClipboard>(&clipboard);

        if (copy == nullptr || !glyphs.paste(*copy, origin)) {
            return false;
        }

        glyph_changed();
        return true;
    }

    bool move_card(CardId id, Pos to) {
        return move_card_impl(id, to, nullptr);
    }

    bool continue_card_move(CardId id, Pos to, Pos origin) {
        return move_card_impl(id, to, &origin);
    }

    bool erase_card(CardId id) {
        return erase_cards(&id, 1);
    }

    bool erase_cards(const CardId* cards, std::size_t count) {
        if (cards == nullptr || count == 0) {
            return false;
        }

        for (std::size_t i = 0; i < count; ++i) {
            if (
                board.find(cards[i]) == nullptr ||
                (i != 0 && cards[i - 1] >= cards[i])
            ) {
                return false;
            }
        }

        CardBatchChange change;
        change.cards.resize(count);

        for (std::size_t i = 0; i < count; ++i) {
            CardChange card{
                .id = cards[i],
                .card = nullptr,
                .card_present = false,
                .edges = {},
            };
            swap_card(card);

            // CardBatchChange restores forward and deletes in reverse.
            change.cards[count - i - 1] = std::move(card);
        }

        history.push(Change{std::move(change)});
        ++revision;
        return true;
    }

    bool undo() {
        if (history.cursor == 0) {
            return false;
        }

        --history.cursor;
        apply_change(history.entries[history.cursor]);
        ++revision;
        return true;
    }

    bool redo() {
        if (history.cursor == history.entries.size()) {
            return false;
        }

        apply_change(history.entries[history.cursor]);
        ++history.cursor;
        ++revision;
        return true;
    }

    void copy_card(CardId id) {
        const Card& card = board.get(id);
        clipboard = CardClipboard{
            .source = id,
            .name = clipboard_card_name(
                card,
                id,
                formats[card.static_format].name
            ),
            .static_format = card.static_format,
            .data = card.data,
        };
    }

    void cut_card(CardId id) {
        copy_card(id);
        erase_card(id);
    }

    CardId paste_card(Pos pos) {
        const CardClipboard* copy =
            std::get_if<CardClipboard>(&clipboard);

        if (copy == nullptr) {
            return kNoCard;
        }

        Card card;
        card.pos = pos;
        card.static_format = copy->static_format;
        card.data = copy->data;
        return add_card(std::move(card));
    }

    void render(
        const Viewport& viewport,
        Rect visible,
        CardId hovered = kNoCard,
        CardId selected = kNoCard,
        EdgeId selected_edge = kNoEdge,
        const EdgePoints* edge_preview = nullptr,
        bool edge_preview_valid = false,
        const Rect* hidden_glyphs = nullptr,
        std::span<const GlyphCell> glyph_preview = {},
        Pos glyph_preview_delta = {}
    ) {
        render_board_span(
            screen,
            board,
            spatial,
            edge_spatial,
            glyphs,
            viewport,
            visible,
            formats,
            session,
            hovered,
            selected,
            selected_edge,
            edge_preview,
            edge_preview_valid,
            hidden_glyphs,
            glyph_preview,
            glyph_preview_delta
        );
    }

    void render_glyph_selection(
        const Viewport& viewport,
        Rect visible,
        Rect selection
    ) {
        draw_world_outline(
            screen,
            selection,
            viewport,
            visible,
            U'░',
            Style{11, 0, AttrBold}
        );
    }

    void render_card_preview(
        const Card& card,
        const Viewport& viewport,
        Rect visible
    ) {
        const CardFormat& format = formats[card.static_format];
        const Rect rect = rect_at(
            card.pos,
            format.measure(card.data)
        );

        if (!overlaps(rect, visible)) {
            return;
        }

        format.draw(
            screen,
            card.data,
            kNoCard,
            static_cast<i32>(card.pos.x - viewport.x),
            static_cast<i32>(card.pos.y - viewport.y),
            format,
            CardVisualState::Selected,
            nullptr
        );
        draw_world_outline(
            screen,
            rect,
            viewport,
            visible,
            U'░',
            Style{10, 0, AttrBold}
        );
    }

    bool load(std::istream& input, u64 size,
              u64 allocation_budget = kMaximumProjectAllocationBytes) {
        Board loaded;
        CardSpatial loaded_spatial;
        GlyphLayer loaded_glyphs;
        if (!whiteboard::io::decode_project(input, size, loaded, loaded_spatial,
                loaded_glyphs, formats, &file_error, allocation_budget)) return false;
        commit_loaded(std::move(loaded), std::move(loaded_spatial),
                      std::move(loaded_glyphs));
        return true;
    }

    void commit_loaded(Board&& loaded, CardSpatial&& loaded_spatial,
                       GlyphLayer&& loaded_glyphs) {
        EdgeSpatial loaded_edges;
        loaded_edges.rebuild(loaded);

        session.end();
        history.clear();
        untracked_dirty = false;
        board = std::move(loaded);
        spatial = std::move(loaded_spatial);
        glyphs = std::move(loaded_glyphs);
        edge_spatial = std::move(loaded_edges);
        ++revision;
    }

    bool mark_saved(u64 expected_revision) {
        if (revision != expected_revision) return false;
        history.mark_saved();
        untracked_dirty = false;
        return true;
    }

    bool dirty() const {
        return document.dirty();
    }

private:
    bool card_rect(const Card& card, Rect& rect) const {
        if (card.static_format >= formats.size()) {
            return false;
        }

        const CardFormat& format = formats[card.static_format];

        if (!card_data_matches(format.data_kind, card.data)) {
            return false;
        }

        const Extent extent = format.measure(card.data);
        return
            extent_in_format(extent, format) &&
            checked_rect_at(card.pos, extent, rect);
    }

    CardChange insert_card(Card&& card) {
        Rect rect;
        const bool valid = card_rect(card, rect);
        (void)valid;
        const CardId id = board.add(std::move(card));
        spatial.change(id, rect);
        std::vector<EdgeGeometryChange> edge_changes;
        card_geometry_changed(
            id,
            {},
            spatial.slots[id].rect,
            &edge_changes
        );
        return {
            .id = id,
            .card = nullptr,
            .card_present = false,
            .edges = std::move(edge_changes),
        };
    }

    bool move_card_impl(
        CardId id,
        Pos to,
        const Pos* drag_origin
    ) {
        if (board.find(id) == nullptr) {
            return false;
        }

        MoveChange change{
            .card = id,
            .pos = to,
            .edges = {},
        };

        if (!swap_move(change)) {
            return false;
        }

        if (
            drag_origin != nullptr &&
            history.cursor == history.entries.size() &&
            history.cursor != 0
        ) {
            MoveChange* previous = std::get_if<MoveChange>(
                &history.entries.back()
            );

            if (
                previous != nullptr &&
                previous->card == id &&
                previous->pos == *drag_origin
            ) {
                if (
                    history.saved_cursor.has_value() &&
                    *history.saved_cursor == history.cursor
                ) {
                    history.saved_cursor.reset();
                }

                if (to == *drag_origin) {
                    history.entries.pop_back();
                    --history.cursor;
                } else {
                    change.pos = *drag_origin;
                    change.edges.clear();
                    *previous = std::move(change);
                }

                ++revision;
                return true;
            }
        }

        history.push(Change{std::move(change)});
        ++revision;
        return true;
    }

    void glyph_changed() {
        untracked_dirty = true;
        ++revision;
    }

    bool swap_move(MoveChange& change) {
        const Card& before = board.get(change.card);
        const Pos previous = before.pos;
        const Rect old_rect = spatial.slots[change.card].rect;

        const i64 width = old_rect.right - old_rect.left;
        const i64 height = old_rect.bottom - old_rect.top;
        Rect new_rect;

        if (
            width <= 0 ||
            height <= 0 ||
            width > std::numeric_limits<i32>::max() ||
            height > std::numeric_limits<i32>::max() ||
            !checked_rect_at(
                change.pos,
                {
                    static_cast<i32>(width),
                    static_cast<i32>(height),
                },
                new_rect
            ) ||
            !board.move(change.card, change.pos)
        ) {
            return false;
        }
        spatial.change(change.card, new_rect);

        if (change.edges.empty()) {
            card_geometry_changed(
                change.card,
                old_rect,
                new_rect,
                &change.edges
            );
        } else {
            swap_edge_geometry(change.edges);
        }

        change.pos = previous;
        return true;
    }

    void swap_card(CardChange& change) {
        if (change.card_present) {
            board.restore(change.id, std::move(*change.card));
            change.card_present = false;

            spatial.change(change.id, spatial.slots[change.id].rect);

            if (change.edges.empty()) {
                card_geometry_changed(
                    change.id,
                    {},
                    spatial.slots[change.id].rect,
                    &change.edges
                );
            } else {
                swap_edge_geometry(change.edges);
            }
            return;
        }

        if (session.active == change.id) {
            session.end();
        }

        const Rect old_rect = spatial.slots[change.id].rect;

        if (change.card == nullptr) {
            change.card = std::make_unique<Card>();
        }

        *change.card = board.take(change.id);
        change.card_present = true;
        spatial.erase(change.id);

        if (change.edges.empty()) {
            card_geometry_changed(
                change.id,
                old_rect,
                {},
                &change.edges
            );
        } else {
            swap_edge_geometry(change.edges);
        }
    }

    void swap_card_data(
        CardId id,
        Card& card,
        CardData& replacement,
        const CardFormat& format
    ) {
        FormatSession* active =
            session.active == id ? &session.state : nullptr;

        std::swap(card.data, replacement);

        if (active == nullptr) {
            return;
        }

        format.begin(*active, card.data);

        if (TextSession* text = std::get_if<TextSession>(active)) {
            TextCardData& current = std::get<TextCardData>(card.data);
            begin_text_syntax(*text, current);
        }
    }

    void swap_card_replace(CardReplaceChange& change) {
        Card& card = board.get(change.id);
        const CardFormat& format = formats[card.static_format];
        const Rect old_rect = spatial.slots[change.id].rect;
        swap_card_data(change.id, card, change.data, format);
        Rect new_rect;

        if (!checked_rect_at(
                card.pos,
                format.measure(card.data),
                new_rect
            )) {
            return;
        }

        if (old_rect == new_rect) {
            return;
        }

        spatial.change(change.id, new_rect);

        if (change.edges.empty()) {
            card_geometry_changed(
                change.id,
                old_rect,
                new_rect,
                &change.edges
            );
        } else {
            swap_edge_geometry(change.edges);
        }
    }

    void swap_edge(EdgeChange& change) {
        if (change.edge.has_value()) {
            board.restore_edge(change.id, std::move(*change.edge));
            change.edge.reset();
            edge_spatial.insert(change.id, board.get_edge(change.id));
            return;
        }

        edge_spatial.erase(change.id, board.get_edge(change.id));
        change.edge.emplace(board.take_edge(change.id));
    }

    void swap_edge_edit(EdgeEditChange& change) {
        edge_spatial.erase(change.id, board.get_edge(change.id));
        board.detach_edge(change.id);
        std::swap(board.get_edge(change.id), change.edge);
        board.attach_edge(change.id);
        edge_spatial.insert(change.id, board.get_edge(change.id));
    }

    void swap_format(FormatChange& change) {
        Card& card = board.get(change.card);
        const CardFormat& format = formats[card.static_format];
        const Rect old_rect = spatial.slots[change.card].rect;
        FormatSession* active =
            session.active == change.card
                ? &session.state
                : nullptr;

        format.swap_undo(card.data, active, change.undo);

        if (!change.layout_changed) {
            return;
        }

        Rect new_rect;

        if (!checked_rect_at(
                card.pos,
                format.measure(card.data),
                new_rect
            )) {
            return;
        }

        if (old_rect != new_rect) {
            spatial.change(change.card, new_rect);

            if (change.edges.empty()) {
                card_geometry_changed(
                    change.card,
                    old_rect,
                    new_rect,
                    &change.edges
                );
            } else {
                swap_edge_geometry(change.edges);
            }
        }
    }

    void apply_change(MoveChange& change) {
        swap_move(change);
    }

    void apply_change(CardChange& change) {
        swap_card(change);
    }

    void apply_change(CardBatchChange& change) {
        if (change.cards.front().card_present) {
            for (CardChange& card : change.cards) {
                swap_card(card);
            }
            return;
        }

        for (auto card = change.cards.rbegin();
             card != change.cards.rend();
             ++card) {
            swap_card(*card);
        }
    }

    void apply_change(CardReplaceChange& change) {
        swap_card_replace(change);
    }

    void apply_change(EdgeChange& change) {
        swap_edge(change);
    }

    void apply_change(EdgeEditChange& change) {
        swap_edge_edit(change);
    }

    void apply_change(FormatChange& change) {
        swap_format(change);
    }

    void apply_change(Change& change) {
        std::visit(
            [this](auto& value) {
                apply_change(value);
            },
            change
        );
    }

    void swap_edge_geometry(
        std::vector<EdgeGeometryChange>& changes
    ) {
        for (EdgeGeometryChange& change : changes) {
            Edge& edge = board.get_edge(change.id);
            edge_spatial.erase(change.id, edge);
            std::swap(edge.state, change.state);

            if (change.points_changed) {
                std::swap(edge.points, change.points);
            }

            if (
                board.find(edge.source.card) != nullptr &&
                board.find(edge.target.card) != nullptr
            ) {
                edge_spatial.insert(change.id, edge);
            }
        }
    }

    void card_geometry_changed(
        CardId card,
        Rect old_rect,
        Rect new_rect,
        std::vector<EdgeGeometryChange>* changes
    ) {
        begin_edge_marks();

        for (EdgeId edge : board.incident[card]) {
            mark_affected_edge(edge);
        }

        collect_edges_in(old_rect);
        collect_edges_in(new_rect);

        if (changes != nullptr) {
            changes->reserve(
                changes->size() + affected_edges.size()
            );
        }

        for (EdgeId id : affected_edges) {
            Edge& edge = board.get_edge(id);
            const bool incident =
                edge.source.card == card || edge.target.card == card;
            const bool endpoints_live =
                board.find(edge.source.card) != nullptr &&
                board.find(edge.target.card) != nullptr;
            const bool repair_ports =
                incident && endpoints_live;

            if (incident) {
                edge_spatial.erase(id, edge);
            }

            if (changes != nullptr) {
                changes->push_back({
                    .id = id,
                    .state = edge.state,
                    .points_changed = repair_ports,
                    .points = repair_ports
                        ? edge.points
                        : EdgePoints{},
                });
            }

            if (repair_ports) {
                repair_edge_ports(spatial, edge);
            }

            if (!endpoints_live) {
                continue;
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

            if (incident) {
                edge_spatial.insert(id, edge);
            }
        }
    }

    void begin_edge_marks() {
        ++edge_mark_generation;

        if (edge_mark_generation == 0) {
            std::fill(edge_marks.begin(), edge_marks.end(), 0);
            ++edge_mark_generation;
        }

        if (edge_marks.size() < board.edges.size()) {
            edge_marks.resize(board.edges.size(), 0);
        }

        affected_edges.clear();
    }

    void mark_affected_edge(EdgeId id) {
        if (edge_marks[id] == edge_mark_generation) {
            return;
        }

        edge_marks[id] = edge_mark_generation;
        affected_edges.push_back(id);
    }

    void collect_edges_in(Rect rect) {
        if (rect.left >= rect.right || rect.top >= rect.bottom) {
            return;
        }

        edge_spatial.query(rect, [&](const EdgeSegmentRef& segment) {
            mark_affected_edge(segment.edge);
            return true;
        });
    }
};
