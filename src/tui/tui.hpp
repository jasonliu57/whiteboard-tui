#pragma once

#include "../app.hpp"
#include "keymap.hpp"
#include "state.hpp"

#include <absl/container/inlined_vector.h>

#include <array>
#include <optional>
#include <string>
#include <vector>

struct TuiHost {
    void* context;
    bool (*command)(void*, TuiAction);
    bool (*input)(void*, InputEvent&) = nullptr;
    bool (*modal)(void*) = nullptr;
    void (*overlay)(void*, Rect) = nullptr;
    void (*status)(void*, std::string&) = nullptr;
    void (*reset)(void*) = nullptr;
};

class Tui {
public:
    Tui(i32 width, i32 height, std::string name, TuiHost host);

    void resize(i32 width, i32 height, bool follow_cursor = true);
    void render();
    bool handle(InputEvent& event);
    bool move_viewport(i64 dx, i64 dy);
    void center_viewport(Pos position);
    void reset_interaction();
    std::string_view status();
    App& app() noexcept { return app_; }
    const Viewport& viewport() const noexcept { return viewport_; }
    void set_name(std::string name) { main_file_ = std::move(name); }
    void set_message(std::string message) { message_ = std::move(message); }

protected:
    TuiHost host_;
    App app_;
    Viewport viewport_;
    Pos board_cursor_{};
    BoardMode board_mode_ = BoardMode::Cursor;
    EdgeModeState edge_mode_;
    GlyphModeState glyph_mode_;
    std::vector<GlyphCell> glyph_writes_;
    absl::InlinedVector<EdgeHit, 8> edge_hits_;
    CardId selected_card_ = kNoCard;
    std::vector<u8> bfs_seen_;
    std::vector<ScreenPos> bfs_queue_;
    std::string main_file_;
    std::string message_;
    std::string status_buffer_;
    CardId frame_hovered_ = kNoCard;
    Pos card_drag_origin_{};
    Pos card_drag_offset_{};
    ScreenPos middle_drag_cell_{};
    bool card_dragging_ = false;
    bool edit_card_on_release_ = false;
    bool middle_dragging_ = false;

    InputContext input_context() const;

    bool handle_board_mouse(const InputEvent& event);

    bool route_text_commands(InputEvent& event);

    bool draw_glyph_text(std::string_view text);

    bool dispatch(TuiAction action);

    void move_edge_cursor(i64 dx, i64 dy);

    void finish_edge_action();

    void begin_edge_source();

    RouteTerminal edge_build_source() const;

    bool edge_leg_reverses(
        const EdgePoints& leg
    ) const;

    void update_edge_preview();

    void commit_edge_waypoint();

    void commit_new_edge();

    void set_edge_build_mode(EdgeBuildMode mode);

    void toggle_manual_elbow();

    void remove_edge_waypoint();

    void collect_edge_hits();

    bool select_edge_at_cursor();

    void cycle_edge_hit();

    void begin_manual_edge_edit();

    void move_edge_segment(i64 dx, i64 dy);

    void commit_manual_edge();

    void reroute_selected_edge();

    void erase_selected_edge();

    void cancel_edge_draft();

    bool handle_active_event(const InputEvent& event);

    void locate_card(CardId id);

    void move_board_focus(i64 dx, i64 dy);

    void begin_glyph_mode();

    void leave_glyph_mode();

    void toggle_glyph_selection();

    void move_glyph_viewport(i64 dx, i64 dy);

    void select_glyph_corner(i64 dx, i64 dy);

    void begin_glyph_placement(i64 dx, i64 dy);

    void move_glyph_placement(i64 dx, i64 dy);

    void commit_glyph_placement();

    void cancel_glyph_placement();

    void convert_glyph_card();

    void convert_text_art_glyphs();

    void copy_glyphs();

    void cut_glyph_selection();

    void paste_glyph_clipboard();

    void erase_glyph_at_cursor();

    void erase_glyph_selection();

    void begin_edge_mode();

    void leave_edge_mode();

    void enter_selection();

    void leave_to_board(Pos position);

    void leave_selection();

    void normalize_selection();

    void normalize_board_mode();

    void select_direction(i32 dx, i32 dy);

    void keep_card_visible(CardId id, i32 dx, i32 dy);

    void move_board_cursor(i64 dx, i64 dy);

    void keep_board_cursor_visible();

    CardId card_under_cursor() const;

    CardId target_card() const;

    CardId require_target_card();

    void new_note();

    void new_markdown();

    void new_code();

    void new_todo();

    void new_csv();

    void new_folder();

    void create_card(Card&& card);

    void finish_card_creation(CardId id);

    void edit_card();

    void move_card(i64 dx, i64 dy);

    bool move_card_to(
        CardId id,
        Pos to,
        const Pos* drag_origin
    );

    void erase_card();

    void copy_card();

    void cut_card();

    void finish_card_removal(Pos position);

    void paste_card();

};
