#pragma once

#include "../board.hpp"
#include "edge_interval_index.hpp"

#include <absl/container/flat_hash_map.h>
#include <absl/container/inlined_vector.h>

#include <algorithm>
#include <cassert>
#include <cstddef>
#include <limits>
#include <utility>
#include <vector>

struct EdgeSpatial {
    EdgeIntervalIndex index;
    std::size_t slot_count = 0;

    void clear() {
        index.clear();
        slot_count = 0;
    }

    void erase(EdgeId id, const Edge& edge) {
        visit_segments(id, edge, [&](EdgeSegmentRef segment) {
            index.erase(segment);
        });
    }

    void insert(EdgeId id, const Edge& edge) {
        slot_count = std::max(
            slot_count,
            static_cast<std::size_t>(id) + 1
        );
        visit_segments(id, edge, [&](EdgeSegmentRef segment) {
            index.insert(segment);
        });
    }

    void rebuild(const Board& board) {
        clear();
        slot_count = board.edges.size();

        for (EdgeId id = 0; id < board.edges.size(); ++id) {
            const Edge* edge = board.find_edge(id);

            if (
                edge == nullptr ||
                board.find(edge->source.card) == nullptr ||
                board.find(edge->target.card) == nullptr
            ) {
                continue;
            }

            insert(id, *edge);
        }
    }

    template<class Visit>
    bool query(Rect rect, Visit&& visit) const {
        return index.query(rect, std::forward<Visit>(visit));
    }

private:
    template<class Visit>
    static void visit_segments(
        EdgeId id,
        const Edge& edge,
        Visit&& visit
    ) {
        for (u32 i = 0; i + 1 < edge.points.size(); ++i) {
            visit({
                .edge = id,
                .segment = i,
                .from = edge.points[i],
                .to = edge.points[i + 1],
            });
        }
    }
};

inline constexpr i64 kCardSpatialCellWidth = 64;
inline constexpr i64 kCardSpatialCellHeight = 32;
inline constexpr u64 kCardSpatialMaximumQueryCells = 65'536;

struct CardSpatialCell {
    i64 x = 0;
    i64 y = 0;

    friend bool operator==(
        const CardSpatialCell&,
        const CardSpatialCell&
    ) = default;

    template<class H>
    friend H AbslHashValue(H state, const CardSpatialCell& cell) {
        return H::combine(std::move(state), cell.x, cell.y);
    }
};

struct CardSpatialCellRange {
    i64 min_x = 0;
    i64 min_y = 0;
    i64 max_x = 0;
    i64 max_y = 0;

    friend bool operator==(
        const CardSpatialCellRange&,
        const CardSpatialCellRange&
    ) = default;
};

inline i64 card_spatial_floor_div(i64 value, i64 divisor) noexcept {
    const i64 quotient = value / divisor;
    const i64 remainder = value % divisor;
    return quotient - static_cast<i64>(remainder < 0);
}

inline CardSpatialCellRange card_spatial_cell_range(Rect rect) noexcept {
    return {
        card_spatial_floor_div(rect.left, kCardSpatialCellWidth),
        card_spatial_floor_div(rect.top, kCardSpatialCellHeight),
        card_spatial_floor_div(
            saturating_sub_i64(rect.right, 1),
            kCardSpatialCellWidth
        ),
        card_spatial_floor_div(
            saturating_sub_i64(rect.bottom, 1),
            kCardSpatialCellHeight
        ),
    };
}

inline bool card_spatial_cell_count(
    CardSpatialCellRange range,
    u64& count
) noexcept {
    i64 width_minus_one = 0;
    i64 height_minus_one = 0;

    if (
        !checked_sub_i64(range.max_x, range.min_x, width_minus_one) ||
        !checked_sub_i64(range.max_y, range.min_y, height_minus_one) ||
        width_minus_one < 0 ||
        height_minus_one < 0
    ) {
        return false;
    }

    const u64 width = static_cast<u64>(width_minus_one) + 1;
    const u64 height = static_cast<u64>(height_minus_one) + 1;

    if (width > std::numeric_limits<u64>::max() / height) {
        return false;
    }

    count = width * height;
    return true;
}

inline bool card_spatial_cell_count(Rect rect, u64& count) noexcept {
    return
        valid_rect(rect) &&
        card_spatial_cell_count(card_spatial_cell_range(rect), count);
}

struct CardSpatialSlot {
    Rect rect{};
    bool alive = false;
};

struct CardSpatial {
    using Bucket = absl::InlinedVector<CardId, 4>;

    std::vector<CardSpatialSlot> slots;

    void clear() {
        cells_.clear();
        slots.clear();
        query_marks_.clear();
        query_generation_ = 0;
        live_count_ = 0;
    }

    void reserve(
        std::size_t slot_count,
        std::size_t estimated_cell_count = 0
    ) {
        slots.reserve(slot_count);
        query_marks_.reserve(slot_count);

        if (estimated_cell_count != 0) {
            cells_.reserve(estimated_cell_count);
        }
    }

    void reset_slots(std::size_t slot_count) {
        clear();
        slots.resize(slot_count);
        query_marks_.resize(slot_count);
    }

    void change(CardId id, Rect rect) {
        assert(valid_rect(rect));

        if (!valid_rect(rect)) {
            return;
        }

        if (id >= slots.size()) {
            slots.resize(static_cast<std::size_t>(id) + 1);
            query_marks_.resize(slots.size());
        }

        CardSpatialSlot& slot = slots[id];

        if (slot.alive) {
            const CardSpatialCellRange old_range =
                card_spatial_cell_range(slot.rect);
            const CardSpatialCellRange new_range =
                card_spatial_cell_range(rect);

            if (old_range == new_range) {
                slot.rect = rect;
                return;
            }

            remove_from_cells(id, old_range);
            slot.rect = rect;
            add_to_cells(id, new_range);
            return;
        }

        slot.rect = rect;
        slot.alive = true;
        ++live_count_;
        add_to_cells(id, card_spatial_cell_range(rect));
    }

    void erase(CardId id) {
        assert(id < slots.size() && slots[id].alive);

        if (id >= slots.size() || !slots[id].alive) {
            return;
        }

        CardSpatialSlot& slot = slots[id];
        remove_from_cells(id, card_spatial_cell_range(slot.rect));
        slot.alive = false;
        --live_count_;
    }

    template<class Visit>
    bool query(Rect rect, Visit&& visit) const {
        if (!valid_rect(rect) || live_count_ == 0) {
            return true;
        }

        const CardSpatialCellRange range = card_spatial_cell_range(rect);
        u64 cell_count = 0;

        if (
            !card_spatial_cell_count(range, cell_count) ||
            cell_count > kCardSpatialMaximumQueryCells
        ) {
            return query_slots(rect, visit);
        }

        const u32 query_generation = begin_query();

        for (i64 y = range.min_y;; ++y) {
            for (i64 x = range.min_x;; ++x) {
                const auto bucket = cells_.find({x, y});

                if (bucket != cells_.end()) {
                    for (CardId id : bucket->second) {
                        if (
                            id >= slots.size() ||
                            query_marks_[id] == query_generation
                        ) {
                            continue;
                        }

                        query_marks_[id] = query_generation;
                        const CardSpatialSlot& slot = slots[id];

                        if (
                            slot.alive &&
                            overlaps(slot.rect, rect) &&
                            !visit(id)
                        ) {
                            return false;
                        }
                    }
                }

                if (x == range.max_x) {
                    break;
                }
            }

            if (y == range.max_y) {
                break;
            }
        }

        return true;
    }

    std::size_t live_count() const noexcept {
        return live_count_;
    }

    std::size_t occupied_cell_count() const noexcept {
        return cells_.size();
    }

    u64 bucket_entry_count() const noexcept {
        u64 count = 0;

        for (const auto& [cell, bucket] : cells_) {
            (void)cell;
            count += bucket.size();
        }

        return count;
    }

    std::size_t maximum_bucket_size() const noexcept {
        std::size_t maximum = 0;

        for (const auto& [cell, bucket] : cells_) {
            (void)cell;
            maximum = std::max(maximum, bucket.size());
        }

        return maximum;
    }

    bool validate() const {
        if (query_marks_.size() != slots.size()) {
            return false;
        }

        std::vector<u32> memberships(slots.size());

        for (const auto& [cell, bucket] : cells_) {
            if (bucket.empty()) {
                return false;
            }

            for (std::size_t i = 0; i < bucket.size(); ++i) {
                const CardId id = bucket[i];

                if (id >= slots.size() || !slots[id].alive) {
                    return false;
                }

                for (std::size_t j = i + 1; j < bucket.size(); ++j) {
                    if (bucket[j] == id) {
                        return false;
                    }
                }

                const CardSpatialCellRange range =
                    card_spatial_cell_range(slots[id].rect);

                if (
                    cell.x < range.min_x ||
                    cell.x > range.max_x ||
                    cell.y < range.min_y ||
                    cell.y > range.max_y ||
                    memberships[id] == std::numeric_limits<u32>::max()
                ) {
                    return false;
                }

                ++memberships[id];
            }
        }

        std::size_t live = 0;

        for (CardId id = 0; id < slots.size(); ++id) {
            const CardSpatialSlot& slot = slots[id];

            if (!slot.alive) {
                if (memberships[id] != 0) {
                    return false;
                }
                continue;
            }

            ++live;
            u64 expected = 0;

            if (
                !card_spatial_cell_count(slot.rect, expected) ||
                expected != memberships[id]
            ) {
                return false;
            }
        }

        return live == live_count_;
    }

private:
    absl::flat_hash_map<CardSpatialCell, Bucket> cells_;
    mutable std::vector<u32> query_marks_;
    mutable u32 query_generation_ = 0;
    std::size_t live_count_ = 0;

    template<class Visit>
    bool query_slots(Rect rect, Visit& visit) const {
        for (CardId id = 0; id < slots.size(); ++id) {
            const CardSpatialSlot& slot = slots[id];

            if (
                slot.alive &&
                overlaps(slot.rect, rect) &&
                !visit(id)
            ) {
                return false;
            }
        }

        return true;
    }

    u32 begin_query() const {
        ++query_generation_;

        if (query_generation_ == 0) {
            std::fill(query_marks_.begin(), query_marks_.end(), 0);
            query_generation_ = 1;
        }

        return query_generation_;
    }

    void add_to_cells(CardId id, CardSpatialCellRange range) {
        for (i64 y = range.min_y;; ++y) {
            for (i64 x = range.min_x;; ++x) {
                cells_[{x, y}].push_back(id);

                if (x == range.max_x) {
                    break;
                }
            }

            if (y == range.max_y) {
                break;
            }
        }
    }

    void remove_from_cells(CardId id, CardSpatialCellRange range) {
        for (i64 y = range.min_y;; ++y) {
            for (i64 x = range.min_x;; ++x) {
                const auto cell = cells_.find({x, y});
                assert(cell != cells_.end());

                if (cell != cells_.end()) {
                    Bucket& bucket = cell->second;
                    const auto entry = std::find(
                        bucket.begin(),
                        bucket.end(),
                        id
                    );
                    assert(entry != bucket.end());

                    if (entry != bucket.end()) {
                        *entry = bucket.back();
                        bucket.pop_back();

                        if (bucket.empty()) {
                            cells_.erase(cell);
                        }
                    }
                }

                if (x == range.max_x) {
                    break;
                }
            }

            if (y == range.max_y) {
                break;
            }
        }
    }
};

inline Rect viewport_rect(const Viewport& view) {
    return rect_at(
        {view.x, view.y},
        {view.width, view.height}
    );
}
