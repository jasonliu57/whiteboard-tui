#pragma once

// Orthogonal edge segments indexed by their long axis.
#include "../types.hpp"

#include <absl/container/btree_map.h>

#include <algorithm>
#include <limits>
#include <vector>

struct EdgeSegmentRef {
    u32 edge = 0;
    u32 segment = 0;
    Pos from{};
    Pos to{};
};

struct IntervalEntry {
    i64 low = 0;
    i64 high = 0;
    EdgeId edge = kNoEdge;
    u32 segment = 0;
};

static_assert(sizeof(IntervalEntry) == 24);

inline bool interval_entry_less(
    const IntervalEntry& first,
    const IntervalEntry& second
) {
    if (first.low != second.low) {
        return first.low < second.low;
    }

    if (first.high != second.high) {
        return first.high < second.high;
    }

    if (first.edge != second.edge) {
        return first.edge < second.edge;
    }

    return first.segment < second.segment;
}

class IntervalTree {
public:
    void insert(IntervalEntry entry) {
        const NodeId inserted = allocate(entry);
        root_ = insert_at(root_, inserted);
    }

    void erase(const IntervalEntry& entry) {
        root_ = erase_at(root_, entry);
    }

    bool empty() const noexcept {
        return root_ == kNoNode;
    }

    template<class Visit>
    bool report_overlaps(
        i64 low,
        i64 high,
        Visit&& visit
    ) const {
        return report_at(root_, low, high, visit);
    }

private:
    using NodeId = u32;
    static constexpr NodeId kNoNode = ~NodeId{0};

    struct Node {
        IntervalEntry entry{};
        i64 max_high = 0;
        NodeId left = kNoNode;
        NodeId right = kNoNode;
        i32 height = 1;
    };

    static_assert(sizeof(Node) == 48);

    std::vector<Node> nodes_;
    NodeId free_head_ = kNoNode;
    NodeId root_ = kNoNode;

    NodeId allocate(IntervalEntry entry) {
        Node node{
            .entry = entry,
            .max_high = entry.high,
        };

        if (free_head_ == kNoNode) {
            const NodeId id = static_cast<NodeId>(nodes_.size());
            nodes_.push_back(node);
            return id;
        }

        const NodeId id = free_head_;
        free_head_ = nodes_[id].left;
        nodes_[id] = node;
        return id;
    }

    void release(NodeId id) {
        nodes_[id].left = free_head_;
        free_head_ = id;
    }

    i32 height(NodeId id) const {
        return id == kNoNode ? 0 : nodes_[id].height;
    }

    i64 max_high(NodeId id) const {
        return id == kNoNode
            ? std::numeric_limits<i64>::min()
            : nodes_[id].max_high;
    }

    void update(NodeId id) {
        Node& node = nodes_[id];
        node.height = 1 + std::max(
            height(node.left),
            height(node.right)
        );
        node.max_high = std::max({
            node.entry.high,
            max_high(node.left),
            max_high(node.right),
        });
    }

    i32 balance_factor(NodeId id) const {
        return height(nodes_[id].left) - height(nodes_[id].right);
    }

    NodeId rotate_left(NodeId root) {
        const NodeId right = nodes_[root].right;
        const NodeId middle = nodes_[right].left;
        nodes_[right].left = root;
        nodes_[root].right = middle;
        update(root);
        update(right);
        return right;
    }

    NodeId rotate_right(NodeId root) {
        const NodeId left = nodes_[root].left;
        const NodeId middle = nodes_[left].right;
        nodes_[left].right = root;
        nodes_[root].left = middle;
        update(root);
        update(left);
        return left;
    }

    NodeId balance(NodeId root) {
        update(root);
        const i32 factor = balance_factor(root);

        if (factor > 1) {
            const NodeId left = nodes_[root].left;

            if (balance_factor(left) < 0) {
                nodes_[root].left = rotate_left(left);
            }
            return rotate_right(root);
        }

        if (factor < -1) {
            const NodeId right = nodes_[root].right;

            if (balance_factor(right) > 0) {
                nodes_[root].right = rotate_right(right);
            }
            return rotate_left(root);
        }

        return root;
    }

    NodeId insert_at(NodeId root, NodeId inserted) {
        if (root == kNoNode) {
            return inserted;
        }

        if (interval_entry_less(
                nodes_[inserted].entry,
                nodes_[root].entry
            )) {
            nodes_[root].left = insert_at(
                nodes_[root].left,
                inserted
            );
        } else {
            nodes_[root].right = insert_at(
                nodes_[root].right,
                inserted
            );
        }
        return balance(root);
    }

    NodeId erase_at(NodeId root, const IntervalEntry& entry) {
        if (root == kNoNode) {
            return kNoNode;
        }

        if (interval_entry_less(entry, nodes_[root].entry)) {
            nodes_[root].left = erase_at(nodes_[root].left, entry);
        } else if (interval_entry_less(nodes_[root].entry, entry)) {
            nodes_[root].right = erase_at(nodes_[root].right, entry);
        } else {
            const NodeId left = nodes_[root].left;
            const NodeId right = nodes_[root].right;

            if (left == kNoNode || right == kNoNode) {
                const NodeId child = left == kNoNode ? right : left;
                release(root);
                return child;
            }

            NodeId successor = right;

            while (nodes_[successor].left != kNoNode) {
                successor = nodes_[successor].left;
            }

            const IntervalEntry replacement = nodes_[successor].entry;
            nodes_[root].entry = replacement;
            nodes_[root].right = erase_at(right, replacement);
        }
        return balance(root);
    }

    template<class Visit>
    bool report_at(
        NodeId root,
        i64 low,
        i64 high,
        Visit& visit
    ) const {
        if (root == kNoNode) {
            return true;
        }

        const Node& node = nodes_[root];

        if (
            node.left != kNoNode &&
            nodes_[node.left].max_high > low
        ) {
            if (!report_at(node.left, low, high, visit)) {
                return false;
            }
        }

        if (
            node.entry.low < high &&
            low < node.entry.high &&
            !visit(node.entry)
        ) {
            return false;
        }

        if (node.entry.low < high) {
            return report_at(node.right, low, high, visit);
        }

        return true;
    }
};

class EdgeIntervalIndex {
public:
    void clear() {
        horizontal_.clear();
        vertical_.clear();
    }

    void insert(EdgeSegmentRef ref) {
        if (ref.from.y == ref.to.y) {
            horizontal_[ref.from.y].insert(horizontal_entry(ref));
        } else {
            vertical_[ref.from.x].insert(vertical_entry(ref));
        }
    }

    void erase(const EdgeSegmentRef& ref) {
        if (ref.from.y == ref.to.y) {
            auto bucket = horizontal_.find(ref.from.y);

            if (bucket == horizontal_.end()) {
                return;
            }

            bucket->second.erase(horizontal_entry(ref));

            if (bucket->second.empty()) {
                horizontal_.erase(bucket);
            }
        } else {
            auto bucket = vertical_.find(ref.from.x);

            if (bucket == vertical_.end()) {
                return;
            }

            bucket->second.erase(vertical_entry(ref));

            if (bucket->second.empty()) {
                vertical_.erase(bucket);
            }
        }
    }

    template<class Visit>
    bool query(Rect rect, Visit&& visit) const {
        auto horizontal = horizontal_.lower_bound(rect.top);

        while (
            horizontal != horizontal_.end() &&
            horizontal->first < rect.bottom
        ) {
            const i64 y = horizontal->first;

            if (!horizontal->second.report_overlaps(
                    rect.left,
                    rect.right,
                    [&](const IntervalEntry& entry) {
                        return visit(EdgeSegmentRef{
                            .edge = entry.edge,
                            .segment = entry.segment,
                            .from = {entry.low, y},
                            .to = {entry.high - 1, y},
                        });
                    }
                )) {
                return false;
            }
            ++horizontal;
        }

        auto vertical = vertical_.lower_bound(rect.left);

        while (
            vertical != vertical_.end() &&
            vertical->first < rect.right
        ) {
            const i64 x = vertical->first;

            if (!vertical->second.report_overlaps(
                    rect.top,
                    rect.bottom,
                    [&](const IntervalEntry& entry) {
                        return visit(EdgeSegmentRef{
                            .edge = entry.edge,
                            .segment = entry.segment,
                            .from = {x, entry.low},
                            .to = {x, entry.high - 1},
                        });
                    }
                )) {
                return false;
            }
            ++vertical;
        }

        return true;
    }

private:
    absl::btree_map<i64, IntervalTree> horizontal_;
    absl::btree_map<i64, IntervalTree> vertical_;

    static IntervalEntry horizontal_entry(EdgeSegmentRef ref) {
        return {
            .low = std::min(ref.from.x, ref.to.x),
            .high = std::max(ref.from.x, ref.to.x) + 1,
            .edge = ref.edge,
            .segment = ref.segment,
        };
    }

    static IntervalEntry vertical_entry(EdgeSegmentRef ref) {
        return {
            .low = std::min(ref.from.y, ref.to.y),
            .high = std::max(ref.from.y, ref.to.y) + 1,
            .edge = ref.edge,
            .segment = ref.segment,
        };
    }
};
