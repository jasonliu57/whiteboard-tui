#pragma once

#include "agent_protocol.hpp"

#include <cstdint>
#include <cstddef>
#include <memory>
#include <optional>
#include <string>

class AgentServer {
public:
    AgentServer();
    ~AgentServer();

    AgentServer(const AgentServer&) = delete;
    AgentServer& operator=(const AgentServer&) = delete;
    AgentServer(AgentServer&&) = delete;
    AgentServer& operator=(AgentServer&&) = delete;

    bool open(std::string path);
    bool active() const noexcept;
    int listener_fd() const noexcept;
    short listener_events() const noexcept;
    std::size_t client_capacity() const noexcept;
    int client_fd(std::size_t slot) const noexcept;
    short client_events(std::size_t slot) const noexcept;
    const std::string& path() const noexcept;
    const std::string& error() const noexcept;
    void handle_listener(short revents);
    void handle_client(std::size_t slot, short revents);
    std::optional<AgentRequest> take_request();
    bool reply(std::uint64_t client, std::string response);
    void expire_clients();

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};
