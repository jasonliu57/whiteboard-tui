#pragma once

#include "../platform/native/app_io.hpp"

#include "native.hpp"
#include "input.hpp"
#include "terminal.hpp"
#include <array>
#include <cerrno>
#include <poll.h>
#include <stdexcept>
#include <unistd.h>

inline NativeTui::NativeTui(i32 width, i32 height, std::string main_file)
    : Tui(width, height, std::move(main_file), TuiHost{
        .context = this,
        .command = [](void* self, TuiAction action) {
            return static_cast<NativeTui*>(self)->native_command(action);
        },
        .input = [](void* self, InputEvent& event) {
            return static_cast<NativeTui*>(self)->native_input(event);
        },
        .modal = [](void* self) {
            return static_cast<NativeTui*>(self)->exporting_folder_ != kNoCard;
        },
        .overlay = [](void* self, Rect visible) {
            auto& tui = *static_cast<NativeTui*>(self);
            if (tui.pending_agent_proposal_) tui.app_.render_card_preview(
                tui.pending_agent_proposal_->card, tui.viewport_, visible);
        },
        .status = [](void* self, std::string& result) {
            static_cast<NativeTui*>(self)->native_status(result);
        },
        .reset = [](void* self) {
            auto& tui = *static_cast<NativeTui*>(self);
            tui.exporting_folder_ = kNoCard;
            tui.export_parent_.clear();
        },
      }) {
    if (::access(main_file_.c_str(), F_OK) == 0) {
        if (!whiteboard::native::load(app_, main_file_)) {
            throw std::runtime_error(app_.file_error);
        }
        message_ = "loaded";
    } else {
        message_ = "new board";
    }

    if (!agent_.open(agent_socket_path())) {
        message_.append(" | ");
        message_.append(agent_.error());
    }
}

inline int NativeTui::run(Terminal& terminal) {
    InputDecoder decoder;
    InputEvent event;
    std::array<char, 4096> input_buffer;
    absl::InlinedVector<pollfd, 10> descriptors;
    absl::InlinedVector<std::size_t, 8> client_slots;
    descriptors.reserve(agent_.client_capacity() + 2);
    client_slots.reserve(agent_.client_capacity());
    bool redraw = true;

    while (running_) {
        if (redraw) {
            render();

            if (!terminal.repaint(app_.screen, status())) {
                return 1;
            }

            redraw = false;
        }

        if (decoder.next(event)) {
            redraw = handle(event) || redraw;
            continue;
        }

        agent_.expire_clients();

        descriptors.clear();
        client_slots.clear();
        const std::size_t terminal_index = descriptors.size();
        descriptors.push_back({
            .fd = STDIN_FILENO,
            .events = POLLIN,
            .revents = 0,
        });

        i32 listener_index = -1;

        if (agent_.listener_events() != 0) {
            listener_index = static_cast<i32>(descriptors.size());
            descriptors.push_back({
                .fd = agent_.listener_fd(),
                .events = agent_.listener_events(),
                .revents = 0,
            });
        }

        const std::size_t first_client_index = descriptors.size();

        for (std::size_t slot = 0;
             slot < agent_.client_capacity();
             ++slot) {
            const short events = agent_.client_events(slot);

            if (events == 0) {
                continue;
            }

            client_slots.push_back(slot);
            descriptors.push_back({
                .fd = agent_.client_fd(slot),
                .events = events,
                .revents = 0,
            });
        }

        const int ready = ::poll(
            descriptors.data(),
            descriptors.size(),
            40
        );

        if (ready < 0) {
            if (errno == EINTR) {
                continue;
            }
            return 1;
        }

        if (terminal.refresh_size()) {
            resize(terminal.width(), terminal.height());
            redraw = true;
        }

        if (
            (descriptors[terminal_index].revents &
             (POLLHUP | POLLERR | POLLNVAL)) != 0
        ) {
            break;
        }

        if ((descriptors[terminal_index].revents & POLLIN) != 0) {
            std::size_t input_size = 0;
            const ReadResult result = terminal.read_input(
                input_buffer,
                input_size
            );

            if (result == ReadResult::Data) {
                decoder.append(std::string_view{
                    input_buffer.data(),
                    input_size,
                });
            } else if (result == ReadResult::Closed) {
                break;
            }
        }

        if (listener_index >= 0) {
            agent_.handle_listener(
                descriptors[listener_index].revents
            );
        }

        for (std::size_t i = 0; i < client_slots.size(); ++i) {
            agent_.handle_client(
                client_slots[i],
                descriptors[first_client_index + i].revents
            );
        }

        if (std::optional<AgentRequest> request =
                agent_.take_request()) {
            redraw = handle_agent_request(std::move(*request)) || redraw;
        }

        if (ready == 0 && decoder.next(event, true)) {
            redraw = handle(event) || redraw;
        }
    }

    return 0;
}
