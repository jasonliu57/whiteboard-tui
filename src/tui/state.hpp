#pragma once

#include "../edge_route.hpp"
#include "../glyph_layer.hpp"
#include "../model.hpp"
#include "../types.hpp"

#include <absl/container/inlined_vector.h>

#include <vector>

enum class BoardMode : u8 {
    Cursor,
    Select,
    Edge,
    Glyph,
};

enum class GlyphPhase : u8 {
    Draw,
    Select,
    Place,
};

struct GlyphPlacement {
    Rect source{};
    Pos original_anchor{};
    Pos original_cursor{};
    Pos delta{};
    std::vector<GlyphCell> cells;
};

struct GlyphModeState {
    GlyphPhase phase = GlyphPhase::Draw;
    Pos anchor{};
    GlyphPlacement placement;
};

inline void clear_glyph_placement(GlyphPlacement& placement) {
    placement.source = {};
    placement.original_anchor = {};
    placement.original_cursor = {};
    placement.delta = {};
    placement.cells.clear();
}

inline void reset_glyph_mode_state(GlyphModeState& state) {
    state.phase = GlyphPhase::Draw;
    state.anchor = {};
    clear_glyph_placement(state.placement);
}

struct ScreenPos {
    i32 x = 0;
    i32 y = 0;
};

enum class EdgePhase : u8 {
    Browse,
    PickTarget,
    EditSegment,
};

enum class EdgeBuildMode : u8 {
    Automatic,
    Manual,
};

constexpr u32 kNoEdgeSegment = ~u32{0};

struct EdgeHit {
    EdgeId edge = kNoEdge;
    u32 segment = kNoEdgeSegment;
};

struct EdgePrefixUndo {
    std::size_t common_size = 0;
    EdgePoints old_suffix;
};

struct EdgeModeState {
    EdgePhase phase = EdgePhase::Browse;
    EdgeEnd source{};
    EdgeId selected = kNoEdge;
    u32 segment = kNoEdgeSegment;
    Edge draft;
    Edge prepared;
    EdgePoints leg;
    EdgePoints fixed_points;
    absl::InlinedVector<EdgePrefixUndo, 4> prefix_undo;
    EdgeBuildMode build_mode = EdgeBuildMode::Automatic;
    bool horizontal_first = true;
    bool target_ready = false;
    bool preview_valid = false;
};

inline void clear_edge_value(Edge& edge) {
    edge.source = {};
    edge.target = {};
    edge.mode = RouteMode::Automatic;
    edge.state = RouteState::Ready;
    edge.route_bounds = {};
    edge.points.clear();
}

inline void reset_edge_mode_state(EdgeModeState& state) {
    state.phase = EdgePhase::Browse;
    state.source = {};
    state.selected = kNoEdge;
    state.segment = kNoEdgeSegment;
    clear_edge_value(state.draft);
    clear_edge_value(state.prepared);
    state.leg.clear();
    state.fixed_points.clear();
    state.prefix_undo.clear();
    state.build_mode = EdgeBuildMode::Automatic;
    state.horizontal_first = true;
    state.target_ready = false;
    state.preview_valid = false;
}
