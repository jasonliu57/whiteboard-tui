#pragma once

#include "generated/protocol_limits.hpp"

#include <cstdint>
#include <string>
#include <string_view>

inline constexpr std::uint32_t kAgentProtocolVersion = 2;

enum class AgentResponseStatus : std::uint8_t {
    Ok,
    Error,
    Invalid,
};

AgentResponseStatus agent_response_status(std::string_view response);

std::string agent_socket_path();

enum class AgentOperation : std::uint8_t {
    Status,
    View,
    ScreenText,
    ScreenPng,
    BoardPng,
    Snapshot,
    GetCard,
    QueryRect,
    CardEdges,
    ProposalStatus,
    ProposeTextCard,
    CreateCards,
    ReplaceCard,
    DeleteCard,
    DeleteCards,
    ConnectCards,
};

enum class AgentBoardLabel : std::uint8_t {
    Name,
    Format,
    CardId,
};

enum class AgentCardKind : std::uint8_t {
    Unknown,
    Note,
    Markdown,
    Code,
};

struct AgentRequest {
    std::uint64_t client = 0;
    AgentOperation operation = AgentOperation::Status;
    std::uint32_t card = 0;
    std::uint32_t target_card = 0;
    std::uint64_t proposal = 0;
    std::uint64_t expected_revision = 0;
    std::uint64_t snapshot_card_cursor = 0;
    std::uint64_t snapshot_edge_cursor = 0;
    std::uint64_t snapshot_glyph_cursor = 0;
    std::int64_t left = 0;
    std::int64_t top = 0;
    std::int64_t right = 0;
    std::int64_t bottom = 0;
    std::uint32_t limit = 0;
    std::uint32_t png_pixels = kAgentPngDefaultPixels;
    std::uint32_t board_png_side = kAgentBoardPngDefaultSide;
    AgentBoardLabel board_label = AgentBoardLabel::Name;
    bool board_viewport = false;
    bool snapshot_revision_set = false;
    bool mutation_revision_set = false;
    AgentCardKind card_kind = AgentCardKind::Unknown;
    std::int64_t x = 0;
    std::int64_t y = 0;
    std::int32_t width = 0;
    std::int32_t height = 0;
    std::string text;
};
