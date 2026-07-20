#pragma once

#include "model.hpp"

#include <absl/container/inlined_vector.h>

#include <cstddef>
#include <optional>
#include <utility>
#include <vector>

struct Board {
    // 槽位順序就是永久渲染順序。
    std::vector<std::optional<Card>> cards;
    std::size_t live_cards = 0;
    std::vector<std::optional<Edge>> edges;
    std::size_t live_edges = 0;

    // 由 Edge endpoints 維持，CardData 不保存 adjacency。
    std::vector<absl::InlinedVector<EdgeId, 4>> incident;

    CardId add(Card&& card) {
        const CardId id = static_cast<CardId>(cards.size());
        cards.emplace_back(std::move(card));
        incident.emplace_back();
        ++live_cards;
        return id;
    }

    Card& get(CardId id) {
        return *cards[id];
    }

    const Card& get(CardId id) const {
        return *cards[id];
    }

    Card* find(CardId id) {
        return
            id < cards.size() && cards[id].has_value()
                ? &*cards[id]
                : nullptr;
    }

    const Card* find(CardId id) const {
        return
            id < cards.size() && cards[id].has_value()
                ? &*cards[id]
                : nullptr;
    }

    Card take(CardId id) {
        Card card = std::move(get(id));
        cards[id].reset();
        --live_cards;
        return card;
    }

    void restore(CardId id, Card&& card) {
        cards[id].emplace(std::move(card));
        ++live_cards;
    }

    bool move(CardId id, Pos to) {
        Card& card = get(id);

        if (card.pos == to) {
            return false;
        }

        card.pos = to;
        return true;
    }

    EdgeId add_edge(Edge&& edge) {
        const EdgeId id = static_cast<EdgeId>(edges.size());
        edges.emplace_back(std::move(edge));
        ++live_edges;
        attach_edge(id);
        return id;
    }

    Edge& get_edge(EdgeId id) {
        return *edges[id];
    }

    const Edge& get_edge(EdgeId id) const {
        return *edges[id];
    }

    Edge* find_edge(EdgeId id) {
        return
            id < edges.size() && edges[id].has_value()
                ? &*edges[id]
                : nullptr;
    }

    const Edge* find_edge(EdgeId id) const {
        return
            id < edges.size() && edges[id].has_value()
                ? &*edges[id]
                : nullptr;
    }

    Edge take_edge(EdgeId id) {
        detach_edge(id);
        Edge edge = std::move(get_edge(id));
        edges[id].reset();
        --live_edges;
        return edge;
    }

    void restore_edge(EdgeId id, Edge&& edge) {
        edges[id].emplace(std::move(edge));
        ++live_edges;
        attach_edge(id);
    }

    void attach_edge(EdgeId id) {
        const Edge& edge = get_edge(id);
        incident[edge.source.card].push_back(id);

        if (edge.target.card != edge.source.card) {
            incident[edge.target.card].push_back(id);
        }
    }

    void detach_edge(EdgeId id) {
        const Edge& edge = get_edge(id);
        remove_incident(edge.source.card, id);

        if (edge.target.card != edge.source.card) {
            remove_incident(edge.target.card, id);
        }
    }

private:
    void remove_incident(CardId card, EdgeId edge) {
        auto& list = incident[card];

        for (std::size_t i = 0; i < list.size(); ++i) {
            if (list[i] == edge) {
                list[i] = list.back();
                list.pop_back();
                return;
            }
        }
    }
};
