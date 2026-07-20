#pragma once

#include "tui.hpp"
#include "../agent_server.hpp"

class Terminal;

enum class AgentProposalState : u8 {
    Committed,
    Rejected,
};

struct AgentProposalResult {
    u64 id = 0;
    AgentProposalState state = AgentProposalState::Rejected;
    CardId card = kNoCard;
};

struct PendingAgentProposal {
    u64 id = 0;
    Card card;
};

class NativeTui : public Tui {
public:
    NativeTui(i32 width, i32 height, std::string main_file);
    int run(Terminal& terminal);

private:
    AgentServer agent_;
    bool running_ = true;
    CardId exporting_folder_ = kNoCard;
    std::string export_parent_;
    std::optional<PendingAgentProposal> pending_agent_proposal_;
    std::array<AgentProposalResult, 64> agent_proposal_results_{};
    std::size_t agent_proposal_result_count_ = 0;
    std::size_t next_agent_proposal_result_ = 0;
    u64 next_agent_proposal_ = 1;
    std::string agent_prefix() const;

    bool append_agent_card(
        std::string& response,
        CardId id
    ) const;

    std::string agent_status_response() const;

    std::string agent_view_response() const;

    std::string agent_screen_text_response() const;

    std::string agent_screen_png_response(u32 font_pixels) const;

    std::string agent_board_png_response(
        u32 max_side,
        AgentBoardLabel label,
        bool show_viewport
    ) const;

    std::string agent_snapshot_response(
        const AgentRequest& request
    ) const;

    std::string agent_get_card_response(CardId id) const;

    std::string agent_query_response(const AgentRequest& request) const;

    std::string agent_edges_response(CardId card) const;

    const AgentProposalResult* find_agent_proposal_result(u64 id) const;

    std::string agent_proposal_status_response(u64 id) const;

    bool begin_agent_proposal(
        const AgentRequest& request,
        std::string& response
    );

    bool create_agent_cards(
        const AgentRequest& request,
        std::string& response
    );

    bool replace_agent_card(
        const AgentRequest& request,
        std::string& response
    );

    bool delete_agent_cards(
        const AgentRequest& request,
        std::string& response
    );

    bool connect_agent_cards(
        const AgentRequest& request,
        std::string& response
    );

    bool handle_agent_request(AgentRequest request);

    void remember_agent_proposal(AgentProposalResult result);

    void accept_agent_proposal();

    void reject_agent_proposal();


    bool native_command(TuiAction action);
    bool native_input(InputEvent& event);
    void native_status(std::string& result);
    void append_export_parent(std::string_view text);
    void begin_folder_export();
    void finish_folder_export();
    void save();
};
