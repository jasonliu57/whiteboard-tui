#include "agent_server.hpp"
#include "platform/posix_fd.hpp"

#include <algorithm>
#include <array>
#include <charconv>
#include <chrono>
#include <cerrno>
#include <deque>
#include <limits>
#include <optional>
#include <poll.h>
#include <string>
#include <string_view>
#include <utility>
#include <sys/socket.h>
#include <sys/stat.h>
#include <unistd.h>

class AgentServer::Impl {
public:
    Impl() = default;

    ~Impl() {
        close_all();
    }

    bool open(std::string path) {
        close_all();
        error_.clear();

        whiteboard::platform::LocalSocketAddress address;

        if (!whiteboard::platform::make_local_socket_address(path, address)) {
            error_ = "invalid agent socket path";
            return false;
        }

        listener_ = whiteboard::platform::open_local_stream();

        if (listener_ < 0) {
            set_error("agent socket");
            return false;
        }

        if (!bind_private(address)) {
            if (
                errno != EADDRINUSE ||
                !replace_stale_socket(path, address)
            ) {
                set_error("agent bind");
                close_listener();
                return false;
            }
        }

        if (!remember_bound_path(std::move(path))) {
            close_listener();
            return false;
        }

        if (::listen(
                listener_,
                static_cast<int>(kMaximumClients)
            ) != 0) {
            set_error("agent listen");
            close_listener();
            unlink_owned_path();
            return false;
        }
        return true;
    }

    bool active() const noexcept {
        return listener_ >= 0;
    }

    int listener_fd() const noexcept {
        return listener_;
    }

    short listener_events() const noexcept {
        return
            listener_ >= 0 &&
            active_client_count() < kMaximumClients
                ? POLLIN
                : 0;
    }

    std::size_t client_capacity() const noexcept {
        return clients_.size();
    }

    int client_fd(std::size_t slot) const noexcept {
        return slot < clients_.size()
            ? clients_[slot].descriptor
            : -1;
    }

    short client_events(std::size_t slot) const noexcept {
        if (slot >= clients_.size()) {
            return 0;
        }

        const Client& client = clients_[slot];

        if (client.descriptor < 0) {
            return 0;
        }

        if (client.output_offset < client.output.size()) {
            return POLLOUT;
        }

        return client.request_complete ? 0 : POLLIN;
    }

    const std::string& path() const noexcept {
        return path_;
    }

    const std::string& error() const noexcept {
        return error_;
    }

    void handle_listener(short revents) {
        if ((revents & POLLIN) == 0) {
            return;
        }

        const int accepted =
            whiteboard::platform::accept_local_stream(listener_);

        if (accepted < 0) {
            if (errno != EAGAIN && errno != EWOULDBLOCK) {
                set_error("agent accept");
            }
            return;
        }

        Client* available = nullptr;

        for (Client& client : clients_) {
            if (client.descriptor < 0) {
                available = &client;
                break;
            }
        }

        if (available == nullptr) {
            ::close(accepted);
            return;
        }

        start_client(*available, accepted);
    }

    void handle_client(std::size_t slot, short revents) {
        if (slot >= clients_.size()) {
            return;
        }

        Client& client = clients_[slot];

        if (client.descriptor < 0) {
            return;
        }

        if ((revents & (POLLERR | POLLNVAL)) != 0) {
            close_client(client);
            return;
        }

        if ((revents & POLLIN) != 0) {
            read_client(client);
        }

        if (client.descriptor >= 0 && (revents & POLLOUT) != 0) {
            write_client(client);
        }

        if (
            client.descriptor >= 0 &&
            (revents & POLLHUP) != 0 &&
            !client.request_complete &&
            client.output.empty()
        ) {
            if (client.input.empty()) {
                close_client(client);
            } else {
                protocol_error(client, "incomplete_request");
            }
        }
    }

    std::optional<AgentRequest> take_request() {
        if (requests_.empty()) {
            return std::nullopt;
        }

        std::optional<AgentRequest> result{
            std::move(requests_.front())
        };
        requests_.pop_front();
        return result;
    }

    bool reply(std::uint64_t client, std::string response) {
        for (Client& state : clients_) {
            if (
                state.descriptor < 0 ||
                state.id != client ||
                !state.request_complete ||
                !state.output.empty()
            ) {
                continue;
            }

            if (response.size() > kAgentResponseLimit) {
                response = "ERR response_too_large\n";
            }

            state.output = std::move(response);
            state.output_offset = 0;
            state.activity = Clock::now();
            return true;
        }

        return false;
    }

    void expire_clients() {
        const auto now = Clock::now();

        for (Client& client : clients_) {
            if (
                client.descriptor >= 0 &&
                now - client.activity >= kClientTimeout
            ) {
                close_client(client);
            }
        }
    }

private:
    using Clock = std::chrono::steady_clock;
    static constexpr std::size_t kMaximumClients = 8;
    static constexpr std::size_t kMaximumRequestBytes =
        kAgentHeaderLimit + 1 + kAgentTextLimit;
    static constexpr auto kClientTimeout =
        std::chrono::milliseconds{kAgentDefaultTimeoutMilliseconds};

    struct Client {
        int descriptor = -1;
        std::uint64_t id = 0;
        std::string input;
        std::string output;
        std::size_t output_offset = 0;
        bool request_complete = false;
        Clock::time_point activity{};
    };

    struct Words {
        std::array<std::string_view, 7> values{};
        std::size_t count = 0;
        bool overflow = false;

        bool empty() const noexcept { return count == 0; }
        std::size_t size() const noexcept { return count; }
        std::string_view operator[](std::size_t i) const {
            return values[i];
        }
    };

    int listener_ = -1;
    std::uint64_t next_client_id_ = 1;
    std::string path_;
    std::string error_;
    std::array<Client, kMaximumClients> clients_{};
    std::deque<AgentRequest> requests_;
    dev_t path_device_ = 0;
    ino_t path_inode_ = 0;
    bool owns_path_ = false;

    std::size_t active_client_count() const noexcept {
        std::size_t count = 0;

        for (const Client& client : clients_) {
            count += client.descriptor >= 0 ? 1U : 0U;
        }

        return count;
    }

    enum class SocketProbe {
        Live,
        Stale,
        Missing,
        Unknown,
    };

    bool bind_private(
        const whiteboard::platform::LocalSocketAddress& address
    ) const {
        const mode_t previous = ::umask(
            S_IXUSR | S_IRWXG | S_IRWXO
        );
        const int result = ::bind(
            listener_,
            reinterpret_cast<const sockaddr*>(&address.value),
            address.size
        );
        const int bind_error = errno;
        ::umask(previous);
        errno = bind_error;
        return result == 0;
    }

    static SocketProbe probe_socket(const std::string& path) {
        const int probe = whiteboard::platform::open_local_stream();

        if (probe < 0) {
            return SocketProbe::Unknown;
        }

        whiteboard::platform::LocalSocketAddress address;

        if (!whiteboard::platform::make_local_socket_address(path, address)) {
            ::close(probe);
            return SocketProbe::Unknown;
        }

        const int result = ::connect(
            probe,
            reinterpret_cast<const sockaddr*>(&address.value),
            address.size
        );
        const int connect_error = errno;
        ::close(probe);

        if (
            result == 0 ||
            connect_error == EINPROGRESS ||
            connect_error == EALREADY ||
            connect_error == EAGAIN
        ) {
            return SocketProbe::Live;
        }

        if (connect_error == ECONNREFUSED) {
            return SocketProbe::Stale;
        }

        if (connect_error == ENOENT) {
            return SocketProbe::Missing;
        }

        return SocketProbe::Unknown;
    }

    bool replace_stale_socket(
        const std::string& path,
        const whiteboard::platform::LocalSocketAddress& address
    ) const {
        struct stat before{};

        if (::lstat(path.c_str(), &before) != 0) {
            if (errno == ENOENT) {
                return bind_private(address);
            }
            return false;
        }

        if (!S_ISSOCK(before.st_mode)) {
            errno = EEXIST;
            return false;
        }

        if (before.st_uid != ::geteuid()) {
            errno = EACCES;
            return false;
        }

        const SocketProbe probe = probe_socket(path);

        if (probe == SocketProbe::Missing) {
            return bind_private(address);
        }

        if (probe != SocketProbe::Stale) {
            errno = EADDRINUSE;
            return false;
        }

        struct stat after{};

        if (
            ::lstat(path.c_str(), &after) != 0 ||
            !S_ISSOCK(after.st_mode) ||
            after.st_uid != ::geteuid() ||
            after.st_dev != before.st_dev ||
            after.st_ino != before.st_ino
        ) {
            errno = EAGAIN;
            return false;
        }

        if (::unlink(path.c_str()) != 0) {
            return false;
        }

        return bind_private(address);
    }

    bool remember_bound_path(std::string path) {
        struct stat status{};

        if (::lstat(path.c_str(), &status) != 0) {
            set_error("agent socket identity");
            return false;
        }

        if (!S_ISSOCK(status.st_mode) || status.st_uid != ::geteuid()) {
            errno = EACCES;
            set_error("agent socket identity");
            return false;
        }

        path_ = std::move(path);
        path_device_ = status.st_dev;
        path_inode_ = status.st_ino;
        owns_path_ = true;
        return true;
    }

    void unlink_owned_path() {
        if (!owns_path_ || path_.empty()) {
            path_.clear();
            owns_path_ = false;
            return;
        }

        struct stat status{};

        if (
            ::lstat(path_.c_str(), &status) == 0 &&
            S_ISSOCK(status.st_mode) &&
            status.st_uid == ::geteuid() &&
            status.st_dev == path_device_ &&
            status.st_ino == path_inode_
        ) {
            ::unlink(path_.c_str());
        }

        path_.clear();
        path_device_ = 0;
        path_inode_ = 0;
        owns_path_ = false;
    }

    void set_error(std::string_view operation) {
        error_.assign(operation);
        error_.append(": ");
        error_.append(std::strerror(errno));
    }

    void close_listener() {
        if (listener_ >= 0) {
            ::close(listener_);
            listener_ = -1;
        }
    }

    void start_client(Client& client, int descriptor) {
        client.descriptor = descriptor;
        client.id = next_client_id_++;

        if (next_client_id_ == 0) {
            next_client_id_ = 1;
        }

        client.input.clear();
        client.output.clear();
        client.output_offset = 0;
        client.request_complete = false;
        client.activity = Clock::now();
    }

    void close_client(Client& client) {
        if (client.descriptor >= 0) {
            ::close(client.descriptor);
        }

        const std::uint64_t id = client.id;
        client = Client{};

        for (auto request = requests_.begin();
             request != requests_.end();) {
            if (request->client == id) {
                request = requests_.erase(request);
            } else {
                ++request;
            }
        }
    }

    void close_all() {
        for (Client& client : clients_) {
            close_client(client);
        }

        requests_.clear();
        close_listener();
        unlink_owned_path();
    }

    void read_client(Client& client) {
        char bytes[16 * 1024];
        const std::size_t remaining =
            kMaximumRequestBytes + 1 - client.input.size();
        const ssize_t count = ::recv(
            client.descriptor,
            bytes,
            std::min(sizeof(bytes), remaining),
            0
        );

        if (count == 0) {
            if (client.input.empty()) {
                close_client(client);
            } else {
                protocol_error(client, "incomplete_request");
            }
            return;
        }

        if (count < 0) {
            if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR) {
                close_client(client);
            }
            return;
        }

        client.input.append(bytes, static_cast<std::size_t>(count));
        client.activity = Clock::now();

        if (client.input.size() > kMaximumRequestBytes) {
            protocol_error(client, "request_too_large");
            return;
        }

        parse_request(client);
    }

    void write_client(Client& client) {
        const ssize_t count = ::send(
            client.descriptor,
            client.output.data() + client.output_offset,
            client.output.size() - client.output_offset,
            whiteboard::platform::no_signal_send_flags()
        );

        if (count < 0) {
            if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR) {
                close_client(client);
            }
            return;
        }

        client.output_offset += static_cast<std::size_t>(count);
        client.activity = Clock::now();

        if (client.output_offset == client.output.size()) {
            close_client(client);
        }
    }

    void protocol_error(Client& client, std::string_view reason) {
        client.request_complete = true;
        client.output = "ERR ";
        client.output.append(reason);
        client.output.push_back('\n');
        client.output_offset = 0;
    }

    template<class Integer>
    static bool parse_integer(std::string_view text, Integer& value) {
        const auto [end, error] = std::from_chars(
            text.data(),
            text.data() + text.size(),
            value
        );
        return error == std::errc{} && end == text.data() + text.size();
    }

    static Words split_words(
        std::string_view line
    ) {
        Words words;

        for (std::size_t begin = 0; begin < line.size();) {
            while (begin < line.size() && line[begin] == ' ') {
                ++begin;
            }

            if (begin == line.size()) {
                break;
            }

            std::size_t end = line.find(' ', begin);

            if (end == std::string_view::npos) {
                end = line.size();
            }

            if (words.count == words.values.size()) {
                words.overflow = true;
                return words;
            }

            words.values[words.count++] = line.substr(begin, end - begin);
            begin = end;
        }

        return words;
    }

    void parse_request(Client& client) {
        const std::size_t newline = client.input.find('\n');

        if (newline == std::string::npos) {
            if (client.input.size() > kAgentHeaderLimit) {
                protocol_error(client, "header_too_large");
            }
            return;
        }

        if (newline > kAgentHeaderLimit) {
            protocol_error(client, "header_too_large");
            return;
        }

        const Words words = split_words(
            std::string_view{client.input}.substr(0, newline)
        );

        if (words.empty()) {
            protocol_error(client, "empty_request");
            return;
        }

        if (words.overflow) {
            protocol_error(client, "unknown_request");
            return;
        }

        AgentRequest request;
        request.client = client.id;
        std::size_t body_size = 0;

        if (words[0] == "STATUS" && words.size() == 1) {
            request.operation = AgentOperation::Status;
        } else if (words[0] == "VIEW" && words.size() == 1) {
            request.operation = AgentOperation::View;
        } else if (words[0] == "SCREEN_TEXT" && words.size() == 1) {
            request.operation = AgentOperation::ScreenText;
        } else if (
            words[0] == "SCREEN_PNG" &&
            (words.size() == 1 || words.size() == 2)
        ) {
            request.operation = AgentOperation::ScreenPng;

            if (
                words.size() == 2 &&
                (!parse_integer(words[1], request.png_pixels) ||
                 request.png_pixels < kAgentPngMinimumPixels ||
                 request.png_pixels > kAgentPngMaximumPixels)
            ) {
                protocol_error(client, "bad_png_resolution");
                return;
            }
        } else if (
            words[0] == "BOARD_PNG" &&
            words.size() <= 4
        ) {
            request.operation = AgentOperation::BoardPng;

            if (
                words.size() >= 2 &&
                (!parse_integer(words[1], request.board_png_side) ||
                 request.board_png_side <
                    kAgentBoardPngMinimumSide ||
                 request.board_png_side >
                    kAgentBoardPngMaximumSide)
            ) {
                protocol_error(client, "bad_board_png");
                return;
            }

            if (words.size() >= 3) {
                if (words[2] == "NAME") {
                    request.board_label = AgentBoardLabel::Name;
                } else if (words[2] == "FORMAT") {
                    request.board_label = AgentBoardLabel::Format;
                } else if (words[2] == "ID") {
                    request.board_label = AgentBoardLabel::CardId;
                } else {
                    protocol_error(client, "bad_board_png");
                    return;
                }
            }

            if (words.size() == 4) {
                if (words[3] != "VIEWPORT") {
                    protocol_error(client, "bad_board_png");
                    return;
                }

                request.board_viewport = true;
            }
        } else if (words[0] == "SNAPSHOT" && words.size() == 5) {
            request.operation = AgentOperation::Snapshot;

            if (words[1] != "-") {
                if (!parse_integer(
                        words[1],
                        request.expected_revision
                    )) {
                    protocol_error(client, "bad_snapshot");
                    return;
                }

                request.snapshot_revision_set = true;
            }

            if (
                !parse_integer(
                    words[2],
                    request.snapshot_card_cursor
                ) ||
                !parse_integer(
                    words[3],
                    request.snapshot_edge_cursor
                ) ||
                !parse_integer(
                    words[4],
                    request.snapshot_glyph_cursor
                )
            ) {
                protocol_error(client, "bad_snapshot");
                return;
            }
        } else if (words[0] == "GET" && words.size() == 2) {
            request.operation = AgentOperation::GetCard;

            if (!parse_integer(words[1], request.card)) {
                protocol_error(client, "bad_card_id");
                return;
            }
        } else if (words[0] == "EDGES" && words.size() == 2) {
            request.operation = AgentOperation::CardEdges;

            if (!parse_integer(words[1], request.card)) {
                protocol_error(client, "bad_card_id");
                return;
            }
        } else if (
            words[0] == "CONNECT" &&
            (words.size() == 3 || words.size() == 4)
        ) {
            request.operation = AgentOperation::ConnectCards;

            if (
                !parse_integer(words[1], request.card) ||
                !parse_integer(words[2], request.target_card) ||
                (words.size() == 4 &&
                 !parse_integer(words[3], request.expected_revision))
            ) {
                protocol_error(client, "bad_connect");
                return;
            }

            request.mutation_revision_set = words.size() == 4;
        } else if (words[0] == "DELETE_CARD" && words.size() == 3) {
            request.operation = AgentOperation::DeleteCard;

            if (
                !parse_integer(words[1], request.card) ||
                !parse_integer(
                    words[2],
                    request.expected_revision
                )
            ) {
                protocol_error(client, "bad_card_delete");
                return;
            }
        } else if (words[0] == "DELETE_CARDS" && words.size() == 3) {
            request.operation = AgentOperation::DeleteCards;
            std::uint64_t parsed_body_size = 0;

            if (
                !parse_integer(
                    words[1],
                    request.expected_revision
                ) ||
                !parse_integer(words[2], parsed_body_size) ||
                parsed_body_size > kAgentTextLimit
            ) {
                protocol_error(client, "bad_card_delete_batch");
                return;
            }

            body_size = static_cast<std::size_t>(parsed_body_size);
        } else if (words[0] == "QUERY" && words.size() == 6) {
            request.operation = AgentOperation::QueryRect;

            if (
                !parse_integer(words[1], request.left) ||
                !parse_integer(words[2], request.top) ||
                !parse_integer(words[3], request.right) ||
                !parse_integer(words[4], request.bottom) ||
                !parse_integer(words[5], request.limit) ||
                request.left >= request.right ||
                request.top >= request.bottom ||
                request.limit == 0 ||
                request.limit > kAgentQueryLimit
            ) {
                protocol_error(client, "bad_query");
                return;
            }
        } else if (words[0] == "PROPOSAL" && words.size() == 2) {
            request.operation = AgentOperation::ProposalStatus;

            if (!parse_integer(words[1], request.proposal)) {
                protocol_error(client, "bad_proposal_id");
                return;
            }
        } else if (words[0] == "PROPOSE" && words.size() == 7) {
            request.operation = AgentOperation::ProposeTextCard;

            if (words[1] == "NOTE") {
                request.card_kind = AgentCardKind::Note;
            } else if (words[1] == "MARKDOWN") {
                request.card_kind = AgentCardKind::Markdown;
            } else if (words[1] == "CODE") {
                request.card_kind = AgentCardKind::Code;
            } else {
                request.card_kind = AgentCardKind::Unknown;
            }

            std::int64_t width = 0;
            std::int64_t height = 0;
            std::uint64_t parsed_body_size = 0;

            if (
                !parse_integer(words[2], request.x) ||
                !parse_integer(words[3], request.y) ||
                !parse_integer(words[4], width) ||
                !parse_integer(words[5], height) ||
                !parse_integer(words[6], parsed_body_size) ||
                width < std::numeric_limits<std::int32_t>::min() ||
                width > std::numeric_limits<std::int32_t>::max() ||
                height < std::numeric_limits<std::int32_t>::min() ||
                height > std::numeric_limits<std::int32_t>::max() ||
                parsed_body_size > kAgentTextLimit
            ) {
                protocol_error(client, "bad_proposal");
                return;
            }

            request.width = static_cast<std::int32_t>(width);
            request.height = static_cast<std::int32_t>(height);
            body_size = static_cast<std::size_t>(parsed_body_size);
        } else if (
            words[0] == "CREATE_CARDS" &&
            (words.size() == 2 || words.size() == 3)
        ) {
            request.operation = AgentOperation::CreateCards;
            std::uint64_t parsed_body_size = 0;
            const std::size_t size_word = words.size() - 1;

            if (
                (words.size() == 3 &&
                 !parse_integer(words[1], request.expected_revision)) ||
                !parse_integer(words[size_word], parsed_body_size) ||
                parsed_body_size > kAgentTextLimit
            ) {
                protocol_error(client, "bad_card_batch");
                return;
            }

            body_size = static_cast<std::size_t>(parsed_body_size);
            request.mutation_revision_set = words.size() == 3;
        } else if (words[0] == "REPLACE_CARD" && words.size() == 6) {
            request.operation = AgentOperation::ReplaceCard;
            std::int64_t width = 0;
            std::int64_t height = 0;
            std::uint64_t parsed_body_size = 0;

            if (
                !parse_integer(words[1], request.card) ||
                !parse_integer(words[2], request.expected_revision) ||
                !parse_integer(words[3], width) ||
                !parse_integer(words[4], height) ||
                !parse_integer(words[5], parsed_body_size) ||
                width < std::numeric_limits<std::int32_t>::min() ||
                width > std::numeric_limits<std::int32_t>::max() ||
                height < std::numeric_limits<std::int32_t>::min() ||
                height > std::numeric_limits<std::int32_t>::max() ||
                parsed_body_size > kAgentTextLimit
            ) {
                protocol_error(client, "bad_card_replace");
                return;
            }

            request.width = static_cast<std::int32_t>(width);
            request.height = static_cast<std::int32_t>(height);
            body_size = static_cast<std::size_t>(parsed_body_size);
        } else {
            protocol_error(client, "unknown_request");
            return;
        }

        const std::size_t total = newline + 1 + body_size;

        if (client.input.size() < total) {
            return;
        }

        if (client.input.size() != total) {
            protocol_error(client, "trailing_bytes");
            return;
        }

        if (body_size != 0) {
            client.input.erase(0, newline + 1);
            request.text = std::move(client.input);
        } else {
            client.input.clear();
        }

        requests_.push_back(std::move(request));
        client.request_complete = true;
    }
};

AgentServer::AgentServer() : impl_(std::make_unique<Impl>()) {}

AgentServer::~AgentServer() = default;

bool AgentServer::open(std::string path) {
    return impl_->open(std::move(path));
}

bool AgentServer::active() const noexcept {
    return impl_->active();
}

int AgentServer::listener_fd() const noexcept {
    return impl_->listener_fd();
}

short AgentServer::listener_events() const noexcept {
    return impl_->listener_events();
}

std::size_t AgentServer::client_capacity() const noexcept {
    return impl_->client_capacity();
}

int AgentServer::client_fd(std::size_t slot) const noexcept {
    return impl_->client_fd(slot);
}

short AgentServer::client_events(std::size_t slot) const noexcept {
    return impl_->client_events(slot);
}

const std::string& AgentServer::path() const noexcept {
    return impl_->path();
}

const std::string& AgentServer::error() const noexcept {
    return impl_->error();
}

void AgentServer::handle_listener(short revents) {
    impl_->handle_listener(revents);
}

void AgentServer::handle_client(std::size_t slot, short revents) {
    impl_->handle_client(slot, revents);
}

std::optional<AgentRequest> AgentServer::take_request() {
    return impl_->take_request();
}

bool AgentServer::reply(std::uint64_t client, std::string response) {
    return impl_->reply(client, std::move(response));
}

void AgentServer::expire_clients() {
    impl_->expire_clients();
}
