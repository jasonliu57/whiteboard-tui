#include "agent_protocol.hpp"

#include "decimal.hpp"

#include <cstdlib>
#include <unistd.h>

AgentResponseStatus agent_response_status(std::string_view response) {
    const std::size_t newline = response.find('\n');

    if (newline == std::string_view::npos) {
        return AgentResponseStatus::Invalid;
    }

    const std::string_view header = response.substr(0, newline);

    if (header == "OK" || header.starts_with("OK ")) {
        return AgentResponseStatus::Ok;
    }

    if (header == "ERR" || header.starts_with("ERR ")) {
        return AgentResponseStatus::Error;
    }

    return AgentResponseStatus::Invalid;
}

std::string agent_socket_path() {
    if (const char* path = std::getenv("WHITEBOARD_TUI_SOCKET")) {
        if (*path != '\0') {
            return path;
        }
    }

    if (const char* runtime = std::getenv("XDG_RUNTIME_DIR")) {
        if (*runtime != '\0') {
            std::string path = runtime;
            path.append("/whiteboard-tui.sock");
            return path;
        }
    }

    std::string path = "/tmp/whiteboard-tui-";
    append_decimal(path, ::getuid());
    path.append(".sock");
    return path;
}
