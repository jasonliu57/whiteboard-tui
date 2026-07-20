#pragma once

#include "tui.hpp"

#include <algorithm>
#include <string_view>

static std::string_view port_side_name(PortSide side) {
    switch (side) {
        case PortSide::Top:    return "top";
        case PortSide::Right:  return "right";
        case PortSide::Bottom: return "bottom";
        case PortSide::Left:   return "left";
    }

    return "?";
}

inline void Tui::move_edge_cursor(i64 dx, i64 dy) {
    if (edge_mode_.phase == EdgePhase::EditSegment) {
        move_edge_segment(dx, dy);
        return;
    }

    move_board_cursor(dx, dy);
    update_edge_preview();
}

inline void Tui::finish_edge_action() {
    switch (edge_mode_.phase) {
        case EdgePhase::Browse:
            if (!select_edge_at_cursor()) {
                begin_edge_source();
                return;
            }
            begin_manual_edge_edit();
            return;

        case EdgePhase::PickTarget:
            if (edge_mode_.target_ready) {
                commit_new_edge();
            } else {
                commit_edge_waypoint();
            }
            return;

        case EdgePhase::EditSegment:
            commit_manual_edge();
            return;
    }
}

inline void Tui::begin_edge_source() {
    const CardId card = card_under_cursor();
    PortSide side;

    if (
        card == kNoCard ||
        !app_.card_port_at(card, board_cursor_, side)
    ) {
        message_ = "source must be on a card border";
        return;
    }

    edge_mode_.phase = EdgePhase::PickTarget;
    edge_mode_.source = {card, side};
    edge_mode_.selected = kNoEdge;
    edge_mode_.segment = kNoEdgeSegment;
    clear_edge_value(edge_mode_.draft);
    clear_edge_value(edge_mode_.prepared);
    edge_mode_.fixed_points.clear();
    edge_mode_.fixed_points.push_back(
        app_.port_geometry(edge_mode_.source).position
    );
    edge_mode_.prefix_undo.clear();
    edge_mode_.build_mode = EdgeBuildMode::Automatic;
    edge_mode_.horizontal_first = true;
    edge_mode_.target_ready = false;
    edge_mode_.preview_valid = false;
    update_edge_preview();
    message_ = "EDGE build: Enter waypoint or target";
}

inline RouteTerminal Tui::edge_build_source() const {
    if (edge_mode_.fixed_points.size() == 1) {
        const PortGeometry port = app_.port_geometry(
            edge_mode_.source
        );
        return {port.position, port.direction, true};
    }

    const Pos position = edge_mode_.fixed_points.back();
    const Pos previous = edge_mode_.fixed_points[
        edge_mode_.fixed_points.size() - 2
    ];
    Pos direction{};

    if (position.x > previous.x) {
        direction.x = 1;
    } else if (position.x < previous.x) {
        direction.x = -1;
    } else if (position.y > previous.y) {
        direction.y = 1;
    } else {
        direction.y = -1;
    }

    return {position, direction, false};
}

inline bool Tui::edge_leg_reverses(
    const EdgePoints& leg
) const {
    if (edge_mode_.fixed_points.size() < 2) {
        return false;
    }

    const Pos join = edge_mode_.fixed_points.back();
    Pos next = join;

    for (Pos point : leg) {
        if (point != join) {
            next = point;
            break;
        }
    }

    if (next == join) {
        return false;
    }

    const Pos previous = edge_mode_.fixed_points[
        edge_mode_.fixed_points.size() - 2
    ];
    const Pos direction{
        join.x == previous.x
            ? 0
            : (join.x > previous.x ? 1 : -1),
        join.y == previous.y
            ? 0
            : (join.y > previous.y ? 1 : -1),
    };
    return direction_dot(join, next, direction) < 0;
}

inline void Tui::update_edge_preview() {
    if (edge_mode_.phase != EdgePhase::PickTarget) {
        return;
    }

    const Rect bounds = viewport_rect(viewport_);
    const RouteTerminal source = edge_build_source();
    RouteTerminal target{board_cursor_, {}, false};
    EdgeEnd target_end{};
    const CardId target_card = card_under_cursor();
    PortSide target_side;

    edge_mode_.target_ready =
        target_card != kNoCard &&
        target_card != edge_mode_.source.card &&
        app_.card_port_at(
            target_card,
            board_cursor_,
            target_side
        );

    if (edge_mode_.target_ready) {
        target_end = {target_card, target_side};
        const PortGeometry port = app_.port_geometry(target_end);
        target = {port.position, port.direction, true};
    }

    EdgePoints& leg = edge_mode_.leg;
    bool generated = false;

    if (edge_mode_.build_mode == EdgeBuildMode::Automatic) {
        generated = app_.route_edge_leg_preview(
            source,
            target,
            bounds,
            edge_mode_.fixed_points,
            leg
        );

        if (!generated) {
            make_manual_edge_leg(
                source,
                target,
                edge_mode_.horizontal_first,
                leg
            );
        }
    } else {
        const Pos start = source.port
            ? add_position(source.position, source.direction)
            : source.position;
        const Pos goal = target.port
            ? add_position(target.position, target.direction)
            : target.position;
        generated =
            contains(bounds, start) &&
            contains(bounds, goal);
        make_manual_edge_leg(
            source,
            target,
            edge_mode_.horizontal_first,
            leg
        );
    }

    const bool reverses = edge_leg_reverses(leg);
    Edge& preview = edge_mode_.prepared;
    preview.source = edge_mode_.source;
    preview.target = {};

    if (edge_mode_.target_ready) {
        preview.target = target_end;
    }

    preview.mode =
        edge_mode_.prefix_undo.empty() &&
        edge_mode_.build_mode == EdgeBuildMode::Automatic
            ? RouteMode::Automatic
            : RouteMode::Manual;
    preview.route_bounds = bounds;
    preview.points = edge_mode_.fixed_points;

    for (Pos point : leg) {
        append_edge_point(preview.points, point);
    }

    if (!reverses) {
        normalize_edge_points(preview.points);
    }

    const EdgeEnd* target_pointer =
        edge_mode_.target_ready ? &preview.target : nullptr;
    const bool advances =
        edge_mode_.target_ready ||
        preview.points != edge_mode_.fixed_points;
    edge_mode_.preview_valid =
        generated &&
        !reverses &&
        advances &&
        (edge_mode_.build_mode == EdgeBuildMode::Automatic
            ? validate_edge_ports(
                app_.board,
                app_.spatial,
                preview.source,
                target_pointer,
                preview.points
            )
            : app_.validate_edge_draft(
                preview.source,
                target_pointer,
                preview.points
            ));
}

inline void Tui::commit_edge_waypoint() {
    if (!edge_mode_.preview_valid) {
        message_ = "invalid waypoint";
        return;
    }

    const EdgePoints& next = edge_mode_.prepared.points;
    std::size_t common_size = 0;

    while (
        common_size < edge_mode_.fixed_points.size() &&
        common_size < next.size() &&
        edge_mode_.fixed_points[common_size] == next[common_size]
    ) {
        ++common_size;
    }

    EdgePrefixUndo undo;
    undo.common_size = common_size;
    undo.old_suffix.reserve(
        edge_mode_.fixed_points.size() - common_size
    );
    undo.old_suffix.insert(
        undo.old_suffix.end(),
        edge_mode_.fixed_points.begin() + common_size,
        edge_mode_.fixed_points.end()
    );
    edge_mode_.prefix_undo.push_back(std::move(undo));
    edge_mode_.fixed_points.swap(edge_mode_.prepared.points);
    update_edge_preview();
    message_ = "waypoint committed:";
    append_decimal(message_, edge_mode_.prefix_undo.size());
}

inline void Tui::commit_new_edge() {
    if (!edge_mode_.preview_valid) {
        message_ = "no route in current viewport";
        return;
    }

    const EdgeId id = app_.add_edge(std::move(edge_mode_.prepared));

    if (id == kNoEdge) {
        message_ = "edge capacity reached";
        return;
    }

    edge_mode_.phase = EdgePhase::Browse;
    edge_mode_.selected = id;
    edge_mode_.segment = kNoEdgeSegment;
    clear_edge_value(edge_mode_.draft);
    clear_edge_value(edge_mode_.prepared);
    edge_mode_.fixed_points.clear();
    edge_mode_.prefix_undo.clear();
    edge_mode_.target_ready = false;
    edge_mode_.preview_valid = false;
    message_ = "edge created:";
    append_decimal(message_, id);
}

inline void Tui::set_edge_build_mode(EdgeBuildMode mode) {
    if (edge_mode_.phase != EdgePhase::PickTarget) {
        return;
    }

    edge_mode_.build_mode = mode;
    update_edge_preview();
    message_ = mode == EdgeBuildMode::Automatic
        ? "build leg: automatic"
        : "build leg: manual L";
}

inline void Tui::toggle_manual_elbow() {
    if (edge_mode_.build_mode != EdgeBuildMode::Manual) {
        message_ = "Tab changes elbow in manual mode";
        return;
    }

    edge_mode_.horizontal_first =
        !edge_mode_.horizontal_first;
    update_edge_preview();
    message_ = edge_mode_.horizontal_first
        ? "manual elbow: horizontal first"
        : "manual elbow: vertical first";
}

inline void Tui::remove_edge_waypoint() {
    if (
        edge_mode_.phase != EdgePhase::PickTarget ||
        edge_mode_.prefix_undo.empty()
    ) {
        message_ = "no waypoint";
        return;
    }

    EdgePrefixUndo undo = std::move(
        edge_mode_.prefix_undo.back()
    );
    edge_mode_.prefix_undo.pop_back();
    edge_mode_.fixed_points.resize(undo.common_size);
    edge_mode_.fixed_points.insert(
        edge_mode_.fixed_points.end(),
        undo.old_suffix.begin(),
        undo.old_suffix.end()
    );
    update_edge_preview();
    message_ = "waypoint removed";
}

inline void Tui::collect_edge_hits() {
    edge_hits_.clear();
    const i64 screen_x = board_cursor_.x - viewport_.x;
    const i64 screen_y = board_cursor_.y - viewport_.y;

    if (
        screen_x < 0 || screen_x >= viewport_.width ||
        screen_y < 0 || screen_y >= viewport_.height
    ) {
        return;
    }

    app_.screen.visit_edge_strokes(
        static_cast<i32>(screen_x),
        static_cast<i32>(screen_y),
        [&](const EdgeStroke& stroke) {
            if (
                stroke.edge == kNoEdge
            ) {
                return;
            }

            for (const EdgeHit& hit : edge_hits_) {
                if (
                    hit.edge == stroke.edge &&
                    hit.segment == stroke.segment
                ) {
                    return;
                }
            }

            edge_hits_.push_back({stroke.edge, stroke.segment});
        }
    );
}

inline bool Tui::select_edge_at_cursor() {
    collect_edge_hits();

    if (edge_hits_.empty()) {
        return false;
    }

    for (const EdgeHit& hit : edge_hits_) {
        if (
            hit.edge == edge_mode_.selected &&
            hit.segment == edge_mode_.segment
        ) {
            return true;
        }
    }

    edge_mode_.selected = edge_hits_.front().edge;
    edge_mode_.segment = edge_hits_.front().segment;
    return true;
}

inline void Tui::cycle_edge_hit() {
    collect_edge_hits();

    if (edge_hits_.empty()) {
        edge_mode_.selected = kNoEdge;
        edge_mode_.segment = kNoEdgeSegment;
        message_ = "no edge";
        return;
    }

    std::size_t next = 0;

    for (std::size_t i = 0; i < edge_hits_.size(); ++i) {
        if (
            edge_hits_[i].edge == edge_mode_.selected &&
            edge_hits_[i].segment == edge_mode_.segment
        ) {
            next = (i + 1) % edge_hits_.size();
            break;
        }
    }

    edge_mode_.selected = edge_hits_[next].edge;
    edge_mode_.segment = edge_hits_[next].segment;
    message_ = "edge selected:";
    append_decimal(message_, edge_mode_.selected);
}

inline void Tui::begin_manual_edge_edit() {
    if (
        edge_mode_.selected == kNoEdge &&
        !select_edge_at_cursor()
    ) {
        message_ = "no edge";
        return;
    }

    const Edge& edge = app_.board.get_edge(edge_mode_.selected);
    const u32 segment = edge_mode_.segment;

    if (
        segment == kNoEdgeSegment ||
        segment + 1 >= edge.points.size()
    ) {
        message_ = "select an edge segment";
        return;
    }

    if (segment == 0 || segment + 2 == edge.points.size()) {
        message_ = "endpoint segment is locked";
        return;
    }

    edge_mode_.phase = EdgePhase::EditSegment;
    edge_mode_.draft = edge;
    edge_mode_.prepared = edge_mode_.draft;
    edge_mode_.preview_valid = app_.prepare_manual_edge(
        edge_mode_.prepared
    );
    message_ = "manual segment:";
    append_decimal(message_, segment);
}

inline void Tui::move_edge_segment(i64 dx, i64 dy) {
    const u32 segment = edge_mode_.segment;
    EdgePoints& points = edge_mode_.draft.points;

    if (segment + 1 >= points.size()) {
        return;
    }

    Pos& first = points[segment];
    Pos& second = points[segment + 1];
    Pos moved_first;
    Pos moved_second;

    if (first.y == second.y && dy != 0 && dx == 0) {
        if (
            !checked_translate(first, {0, dy}, moved_first) ||
            !checked_translate(second, {0, dy}, moved_second)
        ) {
            message_ = "coordinate boundary";
            return;
        }
    } else if (first.x == second.x && dx != 0 && dy == 0) {
        if (
            !checked_translate(first, {dx, 0}, moved_first) ||
            !checked_translate(second, {dx, 0}, moved_second)
        ) {
            message_ = "coordinate boundary";
            return;
        }
    } else {
        message_ = first.y == second.y
            ? "horizontal segment moves up/down"
            : "vertical segment moves left/right";
        return;
    }

    first = moved_first;
    second = moved_second;

    edge_mode_.prepared = edge_mode_.draft;
    edge_mode_.preview_valid = app_.prepare_manual_edge(
        edge_mode_.prepared
    );
    message_ = edge_mode_.preview_valid
        ? "manual preview"
        : "manual preview blocked";
}

inline void Tui::commit_manual_edge() {
    if (!edge_mode_.preview_valid) {
        message_ = "invalid manual route";
        return;
    }

    app_.commit_manual_edge(
        edge_mode_.selected,
        std::move(edge_mode_.prepared)
    );

    edge_mode_.phase = EdgePhase::Browse;
    edge_mode_.segment = kNoEdgeSegment;
    clear_edge_value(edge_mode_.draft);
    clear_edge_value(edge_mode_.prepared);
    edge_mode_.preview_valid = false;
    message_ = "manual edge committed";
}

inline void Tui::reroute_selected_edge() {
    if (
        edge_mode_.selected == kNoEdge &&
        !select_edge_at_cursor()
    ) {
        message_ = "no edge";
        return;
    }

    if (!app_.reroute_edge(
            edge_mode_.selected,
            viewport_rect(viewport_)
        )) {
        message_ = "no route in current viewport";
        return;
    }

    edge_mode_.phase = EdgePhase::Browse;
    edge_mode_.segment = kNoEdgeSegment;
    clear_edge_value(edge_mode_.draft);
    clear_edge_value(edge_mode_.prepared);
    edge_mode_.preview_valid = false;
    message_ = "edge rerouted";
}

inline void Tui::erase_selected_edge() {
    if (
        edge_mode_.phase != EdgePhase::Browse ||
        (edge_mode_.selected == kNoEdge &&
         !select_edge_at_cursor())
    ) {
        message_ = "no edge";
        return;
    }

    app_.erase_edge(edge_mode_.selected);
    edge_mode_.selected = kNoEdge;
    edge_mode_.segment = kNoEdgeSegment;
    message_ = "edge deleted";
}

inline void Tui::cancel_edge_draft() {
    edge_mode_.phase = EdgePhase::Browse;
    clear_edge_value(edge_mode_.draft);
    clear_edge_value(edge_mode_.prepared);
    edge_mode_.fixed_points.clear();
    edge_mode_.prefix_undo.clear();
    edge_mode_.build_mode = EdgeBuildMode::Automatic;
    edge_mode_.horizontal_first = true;
    edge_mode_.target_ready = false;
    edge_mode_.preview_valid = false;
    message_ = "edge edit canceled";
}

inline void Tui::begin_edge_mode() {
    if (
        board_mode_ != BoardMode::Cursor &&
        board_mode_ != BoardMode::Select
    ) {
        message_ = "return to board before EDGE mode";
        return;
    }

    if (board_mode_ == BoardMode::Select) {
        board_cursor_ = app_.port_geometry({
            selected_card_,
            PortSide::Right,
        }).position;
        selected_card_ = kNoCard;
    }

    board_mode_ = BoardMode::Edge;
    reset_edge_mode_state(edge_mode_);
    keep_board_cursor_visible();
    message_ = "EDGE: Enter source or edge, Tab cycle";
}

inline void Tui::leave_edge_mode() {
    board_mode_ = BoardMode::Cursor;
    reset_edge_mode_state(edge_mode_);
    keep_board_cursor_visible();
    message_ = "board mode";
}
