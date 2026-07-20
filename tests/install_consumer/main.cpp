#include <agent_protocol.hpp>
#include <board_document.hpp>
#include <render/font_rasterizer.hpp>
#include <storage/api.hpp>

int main() {
    BoardDocument document;
    return
        document.dirty() ||
        agent_response_status("OK\n") != AgentResponseStatus::Ok
            ? 1
            : 0;
}
