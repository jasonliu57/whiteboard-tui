#pragma once

#include "tui.hpp"

#include <algorithm>
#include <limits>
#include <string_view>

static CardId find_directional_card(
    const App& app,
    const Viewport& viewport,
    CardId selected,
    i32 direction_x,
    i32 direction_y,
    std::vector<u8>& seen,
    std::vector<ScreenPos>& queue
) {
    const Rect source = app.spatial.slots[selected].rect;
    const i64 left = saturating_sub_i64(source.left, viewport.x);
    const i64 top = saturating_sub_i64(source.top, viewport.y);
    const i64 right = saturating_sub_i64(
        saturating_sub_i64(source.right, viewport.x),
        1
    );
    const i64 bottom = saturating_sub_i64(
        saturating_sub_i64(source.bottom, viewport.y),
        1
    );
    const Rect visible = viewport_rect(viewport);

    const i64 seed_fixed = direction_x < 0
        ? saturating_sub_i64(left, 1)
        : (direction_x > 0
            ? saturating_add_i64(right, 1)
            : (direction_y < 0
                ? saturating_sub_i64(top, 1)
                : saturating_add_i64(bottom, 1)));
    const i64 seed_limit = direction_x == 0
        ? viewport.height
        : viewport.width;

    if (seed_fixed < 0 || seed_fixed >= seed_limit) {
        queue.clear();
        return kNoCard;
    }

    seen.assign(
        static_cast<std::size_t>(viewport.width) * viewport.height,
        0
    );
    queue.clear();
    queue.reserve(seen.size());

    const auto push = [&](i64 x, i64 y) {
        if (
            x < 0 || x >= viewport.width ||
            y < 0 || y >= viewport.height
        ) {
            return;
        }

        const std::size_t index =
            static_cast<std::size_t>(y) * viewport.width + x;

        if (seen[index] != 0) {
            return;
        }

        seen[index] = 1;
        queue.push_back({static_cast<i32>(x), static_cast<i32>(y)});
    };

    const auto seed_span = [&](i64 first, i64 last, i64 fixed) {
        first = std::max<i64>(0, first);
        last = std::min<i64>(
            direction_x == 0
                ? viewport.width - 1
                : viewport.height - 1,
            last
        );

        if (first > last) {
            return;
        }

        const i64 middle = (first + last) / 2;

        for (i64 offset = 0;
             middle - offset >= first || middle + offset <= last;
             ++offset) {
            if (middle - offset >= first) {
                if (direction_x == 0) {
                    push(middle - offset, fixed);
                } else {
                    push(fixed, middle - offset);
                }
            }

            if (offset != 0 && middle + offset <= last) {
                if (direction_x == 0) {
                    push(middle + offset, fixed);
                } else {
                    push(fixed, middle + offset);
                }
            }
        }
    };

    if (direction_x < 0) {
        seed_span(top, bottom, seed_fixed);
    } else if (direction_x > 0) {
        seed_span(top, bottom, seed_fixed);
    } else if (direction_y < 0) {
        seed_span(left, right, seed_fixed);
    } else {
        seed_span(left, right, seed_fixed);
    }

    for (std::size_t head = 0; head < queue.size(); ++head) {
        const ScreenPos position = queue[head];
        const CardId id = app.screen.at(position.x, position.y).owner;

        if (id != kNoCard && id != selected) {
            const Rect card = app.spatial.slots[id].rect;
            const bool fully_visible = contains(visible, card);
            const Pos world{
                saturating_add_i64(viewport.x, position.x),
                saturating_add_i64(viewport.y, position.y),
            };
            const bool corner =
                (world.x == card.left ||
                 world.x == card.right - 1) &&
                (world.y == card.top ||
                 world.y == card.bottom - 1);

            if (!fully_visible || corner) {
                return id;
            }
        }

        push(
            position.x + direction_x,
            position.y + direction_y
        );

        if (direction_x == 0) {
            push(position.x - 1, position.y);
            push(position.x + 1, position.y);
        } else {
            push(position.x, position.y - 1);
            push(position.x, position.y + 1);
        }
    }

    return kNoCard;
}

inline void Tui::locate_card(CardId id) {
    if (!app_.has_card(id)) {
        message_ = "missing card:";
        append_decimal(message_, id);
        return;
    }

    app_.end_card();
    board_mode_ = BoardMode::Select;
    selected_card_ = id;
    keep_card_visible(id, 0, 0);
    message_ = "located card:";
    append_decimal(message_, id);
}

inline bool Tui::handle_board_mouse(const InputEvent& event) {
    const InputContext context = input_context();

    if (event.mouse == MouseAction::Release) {
        bool edit = false;

        if (
            context == InputContext::BoardSelect &&
            edit_card_on_release_ &&
            card_dragging_ &&
            event.mouse_x >= 0 &&
            event.mouse_x < viewport_.width &&
            event.mouse_y >= 0 &&
            event.mouse_y < viewport_.height
        ) {
            const Pos world{
                saturating_add_i64(viewport_.x, event.mouse_x),
                saturating_add_i64(viewport_.y, event.mouse_y),
            };
            edit = app_.card_at(world) == selected_card_;
        }

        card_dragging_ = false;
        edit_card_on_release_ = false;
        middle_dragging_ = false;

        if (edit) {
            edit_card();
            return true;
        }

        return false;
    }

    if (
        context != InputContext::BoardCursor &&
        context != InputContext::BoardSelect &&
        context != InputContext::ActiveCard
    ) {
        card_dragging_ = false;
        edit_card_on_release_ = false;
        middle_dragging_ = false;
        return false;
    }

    const ScreenPos cell{event.mouse_x, event.mouse_y};

    if (
        cell.x < 0 ||
        cell.x >= viewport_.width ||
        cell.y < 0 ||
        cell.y >= viewport_.height
    ) {
        return false;
    }

    const Pos world{
        saturating_add_i64(viewport_.x, cell.x),
        saturating_add_i64(viewport_.y, cell.y),
    };

    if (context == InputContext::ActiveCard) {
        card_dragging_ = false;
        edit_card_on_release_ = false;
        middle_dragging_ = false;

        if (
            event.mouse == MouseAction::LeftPress &&
            app_.card_at(world) == kNoCard
        ) {
            leave_to_board(world);
            return true;
        }

        return false;
    }

    if (event.mouse == MouseAction::MiddlePress) {
        card_dragging_ = false;
        edit_card_on_release_ = false;
        middle_drag_cell_ = cell;
        middle_dragging_ = true;
        message_.clear();
        return true;
    }

    if (event.mouse == MouseAction::MiddleDrag) {
        if (!middle_dragging_) {
            return false;
        }

        const i64 dx = middle_drag_cell_.x - cell.x;
        const i64 dy = middle_drag_cell_.y - cell.y;
        middle_drag_cell_ = cell;

        if (dx == 0 && dy == 0) {
            return false;
        }

        move_viewport(dx, dy);
        return true;
    }

    if (context == InputContext::BoardSelect) {
        middle_dragging_ = false;

        if (event.mouse == MouseAction::LeftPress) {
            const CardId id = app_.card_at(world);

            if (id == kNoCard) {
                card_dragging_ = false;
                edit_card_on_release_ = false;
                leave_to_board(world);
                return true;
            }

            edit_card_on_release_ = id == selected_card_;
            selected_card_ = id;

            const Pos position = app_.board.get(id).pos;
            card_drag_origin_ = position;
            card_drag_offset_ = {
                saturating_sub_i64(world.x, position.x),
                saturating_sub_i64(world.y, position.y),
            };
            card_dragging_ = true;
            message_ = "selected card:";
            append_decimal(message_, id);
            return true;
        }

        if (
            event.mouse == MouseAction::LeftDrag &&
            card_dragging_
        ) {
            edit_card_on_release_ = false;
            const Pos from = app_.board.get(selected_card_).pos;
            const Pos to{
                saturating_sub_i64(world.x, card_drag_offset_.x),
                saturating_sub_i64(world.y, card_drag_offset_.y),
            };

            if (to == from) {
                return false;
            }

            const Pos* origin = from == card_drag_origin_
                ? nullptr
                : &card_drag_origin_;
            move_card_to(selected_card_, to, origin);
            return true;
        }

        edit_card_on_release_ = false;
        return false;
    }

    card_dragging_ = false;
    edit_card_on_release_ = false;

    switch (event.mouse) {
        case MouseAction::LeftPress:
            middle_dragging_ = false;
            board_cursor_ = world;

            if (const CardId id = app_.card_at(world);
                id != kNoCard) {
                board_mode_ = BoardMode::Select;
                selected_card_ = id;
                message_ = "selected card:";
                append_decimal(message_, id);
                return true;
            }

            message_.clear();
            return true;

        case MouseAction::RightPress:
            middle_dragging_ = false;
            {
                Pos delta;

                if (
                    checked_sub_i64(
                        world.x,
                        board_cursor_.x,
                        delta.x
                    ) &&
                    checked_sub_i64(
                        world.y,
                        board_cursor_.y,
                        delta.y
                    )
                ) {
                    move_viewport(delta.x, delta.y);
                }
            }
            return true;

        default:
            return false;
    }
}

inline void Tui::move_board_focus(i64 dx, i64 dy) {
    if (board_mode_ == BoardMode::Select) {
        select_direction(
            static_cast<i32>(dx),
            static_cast<i32>(dy)
        );
        return;
    }

    move_board_cursor(dx, dy);
}

inline void Tui::enter_selection() {
    if (board_mode_ == BoardMode::Select) {
        return;
    }

    const CardId id = card_under_cursor();

    if (id == kNoCard) {
        message_ = "no card";
        return;
    }

    board_mode_ = BoardMode::Select;
    selected_card_ = id;
    keep_card_visible(id, 0, 0);
    message_ = "selected";
}

inline void Tui::leave_to_board(Pos position) {
    app_.end_card();
    board_cursor_ = position;
    board_mode_ = BoardMode::Cursor;
    selected_card_ = kNoCard;
    keep_board_cursor_visible();
    message_ = "board mode";
}

inline void Tui::leave_selection() {
    leave_to_board(app_.board.get(selected_card_).pos);
}

inline void Tui::normalize_selection() {
    if (board_mode_ != BoardMode::Select) {
        return;
    }

    if (!app_.has_card(selected_card_)) {
        board_mode_ = BoardMode::Cursor;
        selected_card_ = kNoCard;
        keep_board_cursor_visible();
        return;
    }
}

inline void Tui::normalize_board_mode() {
    normalize_selection();

    if (board_mode_ == BoardMode::Glyph) {
        reset_glyph_mode_state(glyph_mode_);
        glyph_mode_.anchor = board_cursor_;
        return;
    }

    if (board_mode_ != BoardMode::Edge) {
        return;
    }

    if (
        edge_mode_.selected != kNoEdge &&
        !app_.has_edge(edge_mode_.selected)
    ) {
        edge_mode_.selected = kNoEdge;
        edge_mode_.segment = kNoEdgeSegment;
    }

    if (edge_mode_.phase != EdgePhase::Browse) {
        cancel_edge_draft();
    }
}

inline void Tui::reset_interaction() {
    app_.end_card();
    if (host_.reset) host_.reset(host_.context);
    board_mode_ = BoardMode::Cursor;
    selected_card_ = kNoCard;
    reset_edge_mode_state(edge_mode_);
    reset_glyph_mode_state(glyph_mode_);
    card_dragging_ = false;
    edit_card_on_release_ = false;
    middle_dragging_ = false;
}

inline void Tui::select_direction(i32 dx, i32 dy) {
    const CardId target = find_directional_card(
        app_,
        viewport_,
        selected_card_,
        dx,
        dy,
        bfs_seen_,
        bfs_queue_
    );

    if (target == kNoCard) {
        message_ = "no card ";

        if (dx < 0) {
            message_.append("left");
        } else if (dx > 0) {
            message_.append("right");
        } else if (dy < 0) {
            message_.append("up");
        } else {
            message_.append("down");
        }

        return;
    }

    selected_card_ = target;
    keep_card_visible(target, dx, dy);
    message_ = "selected card:";
    append_decimal(message_, target);
}

inline void Tui::keep_card_visible(CardId id, i32 dx, i32 dy) {
    const Rect rect = app_.spatial.slots[id].rect;

    const auto keep_axis = [](
        i64 position,
        i32 size,
        i64& view_position,
        i32 view_size,
        i32 direction
    ) {
        const i64 end = saturating_add_i64(position, size);
        const i64 view_end = saturating_add_i64(
            view_position,
            view_size
        );

        if (size <= view_size) {
            if (position < view_position) {
                view_position = position;
            } else if (end > view_end) {
                view_position = saturating_sub_i64(end, view_size);
            }
            return;
        }

        if (direction > 0) {
            view_position = position;
        } else if (direction < 0) {
            view_position = saturating_sub_i64(end, view_size);
        } else if (
            end <= view_position ||
            position >= view_end
        ) {
            view_position = position;
        }
    };

    keep_axis(
        rect.left,
        static_cast<i32>(rect.right - rect.left),
        viewport_.x,
        viewport_.width,
        dx
    );
    keep_axis(
        rect.top,
        static_cast<i32>(rect.bottom - rect.top),
        viewport_.y,
        viewport_.height,
        dy
    );
}

inline void Tui::move_board_cursor(i64 dx, i64 dy) {
    Pos moved;

    if (!checked_translate(board_cursor_, {dx, dy}, moved)) {
        message_ = "coordinate boundary";
        return;
    }

    board_cursor_ = moved;
    keep_board_cursor_visible();
    message_.clear();
}

inline bool Tui::move_viewport(i64 dx, i64 dy) {
    Pos moved_viewport;
    Pos moved_cursor;
    Rect visible;

    if (
        !checked_translate(
            {viewport_.x, viewport_.y},
            {dx, dy},
            moved_viewport
        ) ||
        !checked_translate(board_cursor_, {dx, dy}, moved_cursor) ||
        !checked_rect_at(
            moved_viewport,
            {viewport_.width, viewport_.height},
            visible
        )
    ) {
        message_ = "coordinate boundary";
        return false;
    }

    viewport_.x = moved_viewport.x;
    viewport_.y = moved_viewport.y;
    board_cursor_ = moved_cursor;
    message_.clear();
    return true;
}

static i64 centered_viewport_origin(i64 position, i32 extent) {
    const i64 half = extent / 2;
    const i64 minimum = std::numeric_limits<i64>::min();
    const i64 maximum =
        std::numeric_limits<i64>::max() - static_cast<i64>(extent);

    if (position < minimum + half) {
        return minimum;
    }

    if (position > maximum + half) {
        return maximum;
    }

    return position - half;
}

inline void Tui::center_viewport(Pos position) {
    board_cursor_ = position;
    viewport_.x = centered_viewport_origin(
        position.x,
        viewport_.width
    );
    viewport_.y = centered_viewport_origin(
        position.y,
        viewport_.height
    );
}

inline void Tui::keep_board_cursor_visible() {
    if (board_cursor_.x < viewport_.x) {
        viewport_.x = board_cursor_.x;
    } else if (
        board_cursor_.x >=
            saturating_add_i64(viewport_.x, viewport_.width)
    ) {
        viewport_.x = saturating_add_i64(
            saturating_sub_i64(
                board_cursor_.x,
                viewport_.width
            ),
            1
        );
    }

    if (board_cursor_.y < viewport_.y) {
        viewport_.y = board_cursor_.y;
    } else if (
        board_cursor_.y >=
            saturating_add_i64(viewport_.y, viewport_.height)
    ) {
        viewport_.y = saturating_add_i64(
            saturating_sub_i64(
                board_cursor_.y,
                viewport_.height
            ),
            1
        );
    }
}

inline CardId Tui::card_under_cursor() const {
    return app_.card_at(board_cursor_);
}

inline CardId Tui::target_card() const {
    return board_mode_ == BoardMode::Select
        ? selected_card_
        : card_under_cursor();
}

inline CardId Tui::require_target_card() {
    const CardId id = target_card();

    if (id == kNoCard) {
        message_ = "no card";
    }
    return id;
}

inline void Tui::new_note() {
    create_card(make_plain_text_note(board_cursor_));
}

inline void Tui::new_markdown() {
    create_card(make_markdown_card(board_cursor_));
}

inline void Tui::new_code() {
    create_card(make_code_card(board_cursor_));
}

inline void Tui::new_todo() {
    create_card(make_todo_card(board_cursor_));
}

inline void Tui::new_csv() {
    create_card(make_csv_card(board_cursor_));
}

inline void Tui::new_folder() {
    create_card(make_folder_card(board_cursor_));
}

inline void Tui::create_card(Card&& card) {
    if (board_mode_ == BoardMode::Select) {
        message_ = "leave selection to create";
        return;
    }

    const CardId id = app_.add_card(std::move(card));

    if (id == kNoCard) {
        message_ = "card outside coordinate range";
        return;
    }

    finish_card_creation(id);
}

inline void Tui::finish_card_creation(CardId id) {
    board_mode_ = BoardMode::Select;
    selected_card_ = id;
    keep_card_visible(id, 0, 0);
    app_.begin_card(id);
    message_ = "new ";
    message_.append(app_.card_format_name(id));
}

inline void Tui::edit_card() {
    const CardId id = require_target_card();

    if (id == kNoCard) {
        return;
    }

    board_mode_ = BoardMode::Select;
    selected_card_ = id;
    keep_card_visible(id, 0, 0);
    app_.begin_card(id);
    message_ = "active ";
    message_.append(app_.card_format_name(id));
}

inline void Tui::move_card(i64 dx, i64 dy) {
    const CardId id = require_target_card();

    if (id == kNoCard) {
        return;
    }

    const Pos from = app_.board.get(id).pos;
    Pos to;

    if (!checked_translate(from, {dx, dy}, to)) {
        message_ = "coordinate boundary";
        return;
    }

    move_card_to(id, to, nullptr);
}

inline bool Tui::move_card_to(
    CardId id,
    Pos to,
    const Pos* drag_origin
) {
    if (
        board_mode_ == BoardMode::Select &&
        (to.x < viewport_.x ||
         to.x >= saturating_add_i64(viewport_.x, viewport_.width) ||
         to.y < viewport_.y ||
         to.y >= saturating_add_i64(viewport_.y, viewport_.height))
    ) {
        message_ = "move outside view";
        return false;
    }

    const Pos from = app_.board.get(id).pos;
    const bool moved = drag_origin == nullptr
        ? app_.move_card(id, to)
        : app_.continue_card_move(id, to, *drag_origin);

    if (!moved) {
        message_ = "card unchanged";
        return false;
    }

    if (board_mode_ != BoardMode::Select) {
        Pos delta;
        Pos moved_cursor;

        if (
            checked_sub_i64(to.x, from.x, delta.x) &&
            checked_sub_i64(to.y, from.y, delta.y) &&
            checked_translate(board_cursor_, delta, moved_cursor)
        ) {
            board_cursor_ = moved_cursor;
        } else {
            board_cursor_ = to;
        }

        keep_board_cursor_visible();
    }

    message_ = "card moved";
    return true;
}

inline void Tui::erase_card() {
    const CardId id = require_target_card();

    if (id == kNoCard) {
        return;
    }

    const Pos position = app_.board.get(id).pos;
    app_.erase_card(id);
    finish_card_removal(position);
    message_ = "card deleted";
}

inline void Tui::copy_card() {
    const CardId id = require_target_card();

    if (id == kNoCard) {
        return;
    }

    app_.copy_card(id);
    message_ = "card copied";
}

inline void Tui::cut_card() {
    const CardId id = require_target_card();

    if (id == kNoCard) {
        return;
    }

    const Pos position = app_.board.get(id).pos;
    app_.cut_card(id);
    finish_card_removal(position);
    message_ = "card cut";
}

inline void Tui::finish_card_removal(Pos position) {
    if (board_mode_ != BoardMode::Select) {
        return;
    }

    board_cursor_ = position;
    board_mode_ = BoardMode::Cursor;
    selected_card_ = kNoCard;
    keep_board_cursor_visible();
}

inline void Tui::paste_card() {
    if (board_mode_ == BoardMode::Select) {
        message_ = "leave selection to paste";
        return;
    }

    const CardId id = app_.paste_card(board_cursor_);

    message_ = id == kNoCard
        ? "card paste failed"
        : "card pasted";
}
