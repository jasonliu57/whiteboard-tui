#pragma once

#include "model.hpp"
#include "formats/format.hpp"

#include <cstddef>
#include <memory>
#include <optional>
#include <utility>
#include <variant>
#include <vector>

struct EdgeGeometryChange {
    EdgeId id = kNoEdge;
    RouteState state = RouteState::Ready;
    bool points_changed = false;
    EdgePoints points;
};

struct MoveChange {
    CardId card = kNoCard;
    Pos pos{};
    std::vector<EdgeGeometryChange> edges;
};

struct CardChange {
    CardId id = kNoCard;
    std::unique_ptr<Card> card;
    bool card_present = false;
    std::vector<EdgeGeometryChange> edges;
};

struct CardBatchChange {
    std::vector<CardChange> cards;
};

struct CardReplaceChange {
    CardId id = kNoCard;
    CardData data;
    std::vector<EdgeGeometryChange> edges;
};

struct EdgeChange {
    EdgeId id = kNoEdge;
    std::optional<Edge> edge;
};

struct EdgeEditChange {
    EdgeId id = kNoEdge;
    Edge edge;
};

struct FormatChange {
    CardId card = kNoCard;
    FormatUndo undo;
    bool layout_changed = false;
    std::vector<EdgeGeometryChange> edges;
};

using Change = std::variant<
    MoveChange,
    CardChange,
    CardBatchChange,
    CardReplaceChange,
    EdgeChange,
    EdgeEditChange,
    FormatChange
>;

struct History {
    std::vector<Change> entries;
    std::size_t cursor = 0;
    std::optional<std::size_t> saved_cursor = 0;

    void branch() {
        if (
            saved_cursor.has_value() &&
            *saved_cursor > cursor
        ) {
            saved_cursor.reset();
        }

        entries.erase(entries.begin() + cursor, entries.end());
    }

    void push(Change&& change) {
        branch();
        entries.emplace_back(std::move(change));
        cursor = entries.size();
    }

    void clear() {
        entries.clear();
        cursor = 0;
        saved_cursor = 0;
    }

    void mark_saved() {
        saved_cursor = cursor;
    }

    bool dirty() const {
        return
            !saved_cursor.has_value() ||
            *saved_cursor != cursor;
    }
};
