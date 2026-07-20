#pragma once

#include "board.hpp"
#include "spatial/board_spatial.hpp"

#include <algorithm>
#include <cstddef>
#include <limits>
#include <utility>
#include <vector>

struct PortGeometry {
    Pos position{};
    Pos direction{};
};

struct RouteTerminal {
    Pos position{};
    Pos direction{};
    bool port = false;
};

inline constexpr u32 kMaximumEdgePoints = 4'096;

static Pos edge_card_middle(
    const CardSpatial& spatial,
    CardId card
) {
    const Rect rect = spatial.slots[card].rect;
    return {
        rect.left + (rect.right - rect.left - 1) / 2,
        rect.top + (rect.bottom - rect.top - 1) / 2,
    };
}

static u8 route_direction(Pos direction) {
    if (direction.x > 0) {
        return 1;
    }

    if (direction.y > 0) {
        return 2;
    }

    if (direction.x < 0) {
        return 3;
    }

    return 0;
}

static PortGeometry edge_port_geometry(
    const CardSpatial& spatial,
    EdgeEnd end
) {
    const Rect rect = spatial.slots[end.card].rect;
    const Pos middle = edge_card_middle(spatial, end.card);

    switch (end.side) {
        case PortSide::Top:
            return {{middle.x, rect.top}, {0, -1}};
        case PortSide::Right:
            return {
                {rect.right - 1, middle.y},
                {1, 0}
            };
        case PortSide::Bottom:
            return {
                {middle.x, rect.bottom - 1},
                {0, 1}
            };
        case PortSide::Left:
            return {{rect.left, middle.y}, {-1, 0}};
    }

    return {};
}

static u64 edge_coordinate_distance(i64 first, i64 second) {
    return first < second
        ? static_cast<u64>(second) - static_cast<u64>(first)
        : static_cast<u64>(first) - static_cast<u64>(second);
}

inline void set_facing_edge_ends(
    const CardSpatial& spatial,
    CardId source_card,
    CardId target_card,
    Edge& edge
) {
    const Pos source = edge_card_middle(spatial, source_card);
    const Pos target = edge_card_middle(spatial, target_card);

    if (
        edge_coordinate_distance(source.x, target.x) >=
        edge_coordinate_distance(source.y, target.y)
    ) {
        if (source.x <= target.x) {
            edge.source = {source_card, PortSide::Right};
            edge.target = {target_card, PortSide::Left};
        } else {
            edge.source = {source_card, PortSide::Left};
            edge.target = {target_card, PortSide::Right};
        }
        return;
    }

    if (source.y <= target.y) {
        edge.source = {source_card, PortSide::Bottom};
        edge.target = {target_card, PortSide::Top};
    } else {
        edge.source = {source_card, PortSide::Top};
        edge.target = {target_card, PortSide::Bottom};
    }
}

static Pos add_position(Pos first, Pos second) {
    return {
        saturating_add_i64(first.x, second.x),
        saturating_add_i64(first.y, second.y),
    };
}

static i32 direction_dot(Pos from, Pos to, Pos direction) {
    if (direction.x > 0 || direction.y > 0) {
        const i64 first = direction.x != 0 ? from.x : from.y;
        const i64 second = direction.x != 0 ? to.x : to.y;
        return (second > first) - (second < first);
    }

    const i64 first = direction.x != 0 ? from.x : from.y;
    const i64 second = direction.x != 0 ? to.x : to.y;
    return (first > second) - (first < second);
}

static bool collinear(Pos first, Pos middle, Pos last) {
    return
        (first.x == middle.x && middle.x == last.x) ||
        (first.y == middle.y && middle.y == last.y);
}

static void normalize_edge_points(EdgePoints& points) {
    std::size_t output = 0;

    for (std::size_t input = 0; input < points.size(); ++input) {
        const Pos point = points[input];

        if (output != 0 && points[output - 1] == point) {
            continue;
        }

        points[output++] = point;

        while (
            output >= 3 &&
            collinear(
                points[output - 3],
                points[output - 2],
                points[output - 1]
            )
        ) {
            points[output - 2] = points[output - 1];
            --output;

            if (
                output >= 2 &&
                points[output - 2] == points[output - 1]
            ) {
                --output;
            }
        }
    }

    points.resize(output);
}

static Rect edge_segment_rect(Pos first, Pos second) {
    return {
        std::min(first.x, second.x),
        std::min(first.y, second.y),
        saturating_add_i64(std::max(first.x, second.x), 1),
        saturating_add_i64(std::max(first.y, second.y), 1),
    };
}

static bool edge_route_bounds_valid(Rect bounds) {
    constexpr u64 kMaxRouteCells = 1'000'000;

    if (bounds.right <= bounds.left || bounds.bottom <= bounds.top) {
        return false;
    }

    const u64 width =
        static_cast<u64>(bounds.right) -
        static_cast<u64>(bounds.left);
    const u64 height =
        static_cast<u64>(bounds.bottom) -
        static_cast<u64>(bounds.top);

    return
        width <= kMaxRouteCells &&
        height <= kMaxRouteCells &&
        width <= kMaxRouteCells / height;
}

static bool validate_edge_geometry(
    const EdgePoints& points
) {
    if (
        points.size() < 2 ||
        points.size() > kMaximumEdgePoints
    ) {
        return false;
    }

    for (u32 i = 0; i + 1 < points.size(); ++i) {
        const Pos first = points[i];
        const Pos second = points[i + 1];

        if (
            first.x == std::numeric_limits<i64>::max() ||
            first.y == std::numeric_limits<i64>::max() ||
            second.x == std::numeric_limits<i64>::max() ||
            second.y == std::numeric_limits<i64>::max() ||
            first == second ||
            (first.x != second.x && first.y != second.y)
        ) {
            return false;
        }
    }

    for (u32 i = 0; i + 1 < points.size(); ++i) {
        const Rect first = edge_segment_rect(
            points[i],
            points[i + 1]
        );

        for (u32 j = i + 2; j + 1 < points.size(); ++j) {
            if (overlaps(
                    first,
                    edge_segment_rect(points[j], points[j + 1])
                )) {
                return false;
            }
        }
    }

    return true;
}

static bool validate_edge_ports(
    const Board& board,
    const CardSpatial& spatial,
    EdgeEnd source_end,
    const EdgeEnd* target_end,
    const EdgePoints& points
) {
    if (
        points.size() < 2 ||
        board.find(source_end.card) == nullptr ||
        (target_end != nullptr &&
         (source_end.card == target_end->card ||
          board.find(target_end->card) == nullptr))
    ) {
        return false;
    }

    const PortGeometry source = edge_port_geometry(
        spatial,
        source_end
    );

    if (
        points.front() != source.position ||
        direction_dot(points[0], points[1], source.direction) <= 0
    ) {
        return false;
    }

    if (target_end != nullptr) {
        const PortGeometry target = edge_port_geometry(
            spatial,
            *target_end
        );

        if (
            points.back() != target.position ||
            direction_dot(
                points[points.size() - 2],
                points.back(),
                target.direction
            ) >= 0
        ) {
            return false;
        }
    }

    return true;
}

static bool validate_edge_collision(
    const Board& board,
    const CardSpatial& spatial,
    EdgeEnd source_end,
    const EdgeEnd* target_end,
    const EdgePoints& points
) {
    if (!validate_edge_ports(
            board,
            spatial,
            source_end,
            target_end,
            points
        )) {
        return false;
    }

    for (u32 i = 0; i + 1 < points.size(); ++i) {
        const bool first_segment = i == 0;
        const bool last_segment = i + 2 == points.size();

        const bool clear = spatial.query(
            edge_segment_rect(points[i], points[i + 1]),
            [&](CardId card) {
                if (
                    (card == source_end.card && first_segment) ||
                    (target_end != nullptr &&
                     card == target_end->card && last_segment)
                ) {
                    return true;
                }

                return false;
            }
        );

        if (!clear) {
            return false;
        }
    }

    return true;
}

inline bool validate_edge(
    const Board& board,
    const CardSpatial& spatial,
    const Edge& edge
) {
    return
        validate_edge_geometry(edge.points) &&
        validate_edge_collision(
            board,
            spatial,
            edge.source,
            &edge.target,
            edge.points
        );
}

static void append_edge_point(EdgePoints& points, Pos point) {
    if (points.empty() || points.back() != point) {
        points.push_back(point);
    }
}

inline void make_manual_edge_leg(
    RouteTerminal source,
    RouteTerminal target,
    bool horizontal_first,
    EdgePoints& points
) {
    const Pos start = source.port
        ? add_position(source.position, source.direction)
        : source.position;
    const Pos goal = target.port
        ? add_position(target.position, target.direction)
        : target.position;

    points.clear();
    append_edge_point(points, source.position);
    append_edge_point(points, start);

    if (start.x != goal.x && start.y != goal.y) {
        append_edge_point(
            points,
            horizontal_first
                ? Pos{goal.x, start.y}
                : Pos{start.x, goal.y}
        );
    }

    append_edge_point(points, goal);

    if (target.port) {
        append_edge_point(points, target.position);
    }

    normalize_edge_points(points);
}

static void rebuild_short_edge_ends(
    Edge& edge,
    PortGeometry source,
    PortGeometry target
) {
    const Pos source_stub = add_position(
        source.position,
        source.direction
    );
    const Pos target_stub = add_position(
        target.position,
        target.direction
    );

    edge.points.clear();
    append_edge_point(edge.points, source.position);
    append_edge_point(edge.points, source_stub);

    if (
        source_stub.x != target_stub.x &&
        source_stub.y != target_stub.y
    ) {
        append_edge_point(
            edge.points,
            source.direction.x != 0
                ? Pos{target_stub.x, source_stub.y}
                : Pos{source_stub.x, target_stub.y}
        );
    }

    append_edge_point(edge.points, target_stub);
    append_edge_point(edge.points, target.position);
}

static void rebuild_blocked_edge_ends(
    Edge& edge,
    PortGeometry source,
    PortGeometry target
) {
    edge.points.clear();
    append_edge_point(edge.points, source.position);

    if (source.position == target.position) {
        append_edge_point(
            edge.points,
            add_position(source.position, source.direction)
        );
        return;
    }

    if (
        source.position.x != target.position.x &&
        source.position.y != target.position.y
    ) {
        append_edge_point(edge.points, {
            target.position.x,
            source.position.y,
        });
    }

    append_edge_point(edge.points, target.position);
}

inline void update_edge_ports(
    Edge& edge,
    PortGeometry source,
    PortGeometry target
) {
    if (edge.points.size() < 4) {
        rebuild_short_edge_ends(edge, source, target);
        normalize_edge_points(edge.points);
        return;
    }

    edge.points.front() = source.position;
    edge.points.back() = target.position;

    if (source.direction.x != 0) {
        edge.points[1].y = source.position.y;
    } else {
        edge.points[1].x = source.position.x;
    }

    const std::size_t before_target = edge.points.size() - 2;

    if (target.direction.x != 0) {
        edge.points[before_target].y = target.position.y;
    } else {
        edge.points[before_target].x = target.position.x;
    }

    normalize_edge_points(edge.points);
}

inline void update_edge_ports(
    const CardSpatial& spatial,
    Edge& edge
) {
    update_edge_ports(
        edge,
        edge_port_geometry(spatial, edge.source),
        edge_port_geometry(spatial, edge.target)
    );
}

inline void repair_edge_ports(
    const CardSpatial& spatial,
    Edge& edge
) {
    const PortGeometry source = edge_port_geometry(
        spatial,
        edge.source
    );
    const PortGeometry target = edge_port_geometry(
        spatial,
        edge.target
    );
    update_edge_ports(edge, source, target);

    if (!validate_edge_geometry(edge.points)) {
        rebuild_blocked_edge_ends(edge, source, target);
    }
}

class EdgeRouter {
public:
    bool route(
        const Board& board,
        const CardSpatial& spatial,
        Edge& edge,
        Rect bounds
    ) {
        if (
            edge.source.card == edge.target.card ||
            board.find(edge.source.card) == nullptr ||
            board.find(edge.target.card) == nullptr ||
            !edge_route_bounds_valid(bounds)
        ) {
            return false;
        }

        const PortGeometry source = edge_port_geometry(
            spatial,
            edge.source
        );
        const PortGeometry target = edge_port_geometry(
            spatial,
            edge.target
        );
        EdgePoints points;

        if (!route_leg(
                spatial,
                {source.position, source.direction, true},
                {target.position, target.direction, true},
                bounds,
                nullptr,
                points
            )) {
            return false;
        }

        if (!validate_edge_ports(
                board,
                spatial,
                edge.source,
                &edge.target,
                points
            )) {
            return false;
        }

        edge.route_bounds = bounds;
        edge.points = std::move(points);
        edge.state = RouteState::Ready;
        return true;
    }

    bool route_leg(
        const CardSpatial& spatial,
        RouteTerminal source,
        RouteTerminal target,
        Rect bounds,
        const EdgePoints* prefix,
        EdgePoints& points
    ) {
        if (!edge_route_bounds_valid(bounds)) {
            return false;
        }

        Pos start = source.position;
        Pos goal = target.position;

        if (
            (source.port &&
             !checked_translate(
                source.position,
                source.direction,
                start
             )) ||
            (target.port &&
             !checked_translate(
                target.position,
                target.direction,
                goal
             ))
        ) {
            return false;
        }

        if (!contains(bounds, start) || !contains(bounds, goal)) {
            return false;
        }

        bounds_ = bounds;
        width_ = static_cast<u32>(bounds.right - bounds.left);
        height_ = static_cast<u32>(bounds.bottom - bounds.top);
        const u32 cell_count = width_ * height_;

        blocked_.assign(cell_count, 0);
        spatial.query(bounds, [&](CardId id) {
            const Rect card = spatial.slots[id].rect;
            const Rect clipped{
                std::max(card.left, bounds.left),
                std::max(card.top, bounds.top),
                std::min(card.right, bounds.right),
                std::min(card.bottom, bounds.bottom),
            };

            for (i64 y = clipped.top; y < clipped.bottom; ++y) {
                for (i64 x = clipped.left; x < clipped.right; ++x) {
                    blocked_[cell_index({x, y})] = 1;
                }
            }
            return true;
        });

        if (prefix != nullptr) {
            block_prefix(*prefix);
        }

        const u32 start_cell = cell_index(start);
        const u32 goal_cell = cell_index(goal);

        if (!source.port) {
            blocked_[start_cell] = 0;
        }

        if (blocked_[start_cell] != 0 || blocked_[goal_cell] != 0) {
            return false;
        }

        distance_.assign(cell_count, -1);
        queue_.clear();
        queue_.reserve(cell_count);
        distance_[start_cell] = 0;
        queue_.push_back(start_cell);

        i32 goal_distance = start_cell == goal_cell ? 0 : -1;

        for (std::size_t head = 0; head < queue_.size(); ++head) {
            const u32 cell = queue_[head];

            if (
                goal_distance >= 0 &&
                distance_[cell] >= goal_distance
            ) {
                break;
            }

            const Pos position = cell_position(cell);

            for (u8 direction = 0; direction < 4; ++direction) {
                Pos next;

                if (!checked_translate(
                        position,
                        {
                            kDirectionX[direction],
                            kDirectionY[direction],
                        },
                        next
                    )) {
                    continue;
                }

                if (!contains(bounds, next)) {
                    continue;
                }

                const u32 next_cell = cell_index(next);

                if (
                    blocked_[next_cell] != 0 ||
                    distance_[next_cell] >= 0
                ) {
                    continue;
                }

                distance_[next_cell] = distance_[cell] + 1;
                queue_.push_back(next_cell);

                if (next_cell == goal_cell) {
                    goal_distance = distance_[next_cell];
                }
            }
        }

        if (distance_[goal_cell] < 0) {
            return false;
        }

        constexpr i32 kNoTurnCost = std::numeric_limits<i32>::max();
        constexpr u32 kNoParent = ~u32{0};
        turns_.assign(static_cast<std::size_t>(cell_count) * 4, kNoTurnCost);
        parent_.assign(static_cast<std::size_t>(cell_count) * 4, kNoParent);

        const u8 source_direction = route_direction(source.direction);
        turns_[start_cell * 4 + source_direction] = 0;

        for (u32 cell : queue_) {
            if (distance_[cell] >= distance_[goal_cell]) {
                break;
            }

            const Pos position = cell_position(cell);

            for (u8 previous = 0; previous < 4; ++previous) {
                const u32 state = cell * 4 + previous;

                if (turns_[state] == kNoTurnCost) {
                    continue;
                }

                for (u8 direction = 0; direction < 4; ++direction) {
                    Pos next;

                    if (!checked_translate(
                            position,
                            {
                                kDirectionX[direction],
                                kDirectionY[direction],
                            },
                            next
                        )) {
                        continue;
                    }

                    if (!contains(bounds, next)) {
                        continue;
                    }

                    const u32 next_cell = cell_index(next);

                    if (distance_[next_cell] != distance_[cell] + 1) {
                        continue;
                    }

                    const i32 cost = turns_[state] +
                        (previous == direction ? 0 : 1);
                    const u32 next_state = next_cell * 4 + direction;

                    if (cost < turns_[next_state]) {
                        turns_[next_state] = cost;
                        parent_[next_state] = state;
                    }
                }
            }
        }

        u32 state = kNoParent;
        i32 best = kNoTurnCost;

        for (u8 direction = 0; direction < 4; ++direction) {
            const u32 candidate = goal_cell * 4 + direction;

            if (turns_[candidate] == kNoTurnCost) {
                continue;
            }

            i32 cost = turns_[candidate];

            if (target.port) {
                const Pos inward{
                    -target.direction.x,
                    -target.direction.y,
                };
                cost += direction == route_direction(inward) ? 0 : 1;
            }

            if (cost < best) {
                best = cost;
                state = candidate;
            }
        }

        if (state == kNoParent) {
            return false;
        }

        points.clear();
        if (target.port) {
            points.push_back(target.position);
        }

        u32 cell = state / 4;
        u8 direction = static_cast<u8>(state % 4);
        append_edge_point(points, cell_position(cell));

        while (cell != start_cell) {
            state = parent_[state];
            const u32 previous_cell = state / 4;
            const u8 previous_direction = static_cast<u8>(state % 4);

            if (previous_direction != direction) {
                append_edge_point(
                    points,
                    cell_position(previous_cell)
                );
            }

            cell = previous_cell;
            direction = previous_direction;
        }

        append_edge_point(points, start);

        if (source.port) {
            append_edge_point(points, source.position);
        }

        std::reverse(points.begin(), points.end());
        normalize_edge_points(points);
        return true;
    }

private:
    static constexpr i64 kDirectionX[4] = {0, 1, 0, -1};
    static constexpr i64 kDirectionY[4] = {-1, 0, 1, 0};

    Rect bounds_{};
    u32 width_ = 0;
    u32 height_ = 0;
    std::vector<u8> blocked_;
    std::vector<i32> distance_;
    std::vector<u32> queue_;
    std::vector<i32> turns_;
    std::vector<u32> parent_;

    u32 cell_index(Pos position) const {
        return static_cast<u32>(
            (position.y - bounds_.top) * width_ +
            position.x - bounds_.left
        );
    }

    Pos cell_position(u32 cell) const {
        return {
            saturating_add_i64(bounds_.left, cell % width_),
            saturating_add_i64(bounds_.top, cell / width_),
        };
    }

    void block_prefix(const EdgePoints& prefix) {
        for (u32 i = 0; i + 1 < prefix.size(); ++i) {
            const Rect segment = edge_segment_rect(
                prefix[i],
                prefix[i + 1]
            );
            const Rect clipped{
                std::max(segment.left, bounds_.left),
                std::max(segment.top, bounds_.top),
                std::min(segment.right, bounds_.right),
                std::min(segment.bottom, bounds_.bottom),
            };

            for (i64 y = clipped.top; y < clipped.bottom; ++y) {
                for (i64 x = clipped.left; x < clipped.right; ++x) {
                    blocked_[cell_index({x, y})] = 1;
                }
            }
        }
    }
};
