#include "agent_protocol.hpp"
#include "decimal.hpp"
#include "platform/posix_fd.hpp"
#include "storage/atomic_file.hpp"
#include "verification/canonical_snapshot.hpp"

#include <algorithm>
#include <array>
#include <charconv>
#include <cerrno>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <string>
#include <string_view>
#include <poll.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

static void usage() {
    std::cerr <<
        "usage:\n"
        "  whiteboardctl status\n"
        "  whiteboardctl view\n"
        "  whiteboardctl screen-text\n"
        "  whiteboardctl screen-png [FONT_PIXELS]\n"
        "  whiteboardctl board-png [MAX_SIDE] [name|format|id] [viewport]\n"
        "  whiteboardctl snapshot --output FILE\n"
        "  whiteboardctl get CARD\n"
        "  whiteboardctl query LEFT TOP RIGHT BOTTOM [LIMIT]\n"
        "  whiteboardctl edges CARD\n"
        "  whiteboardctl connect SOURCE_CARD TARGET_CARD [REVISION]\n"
        "  whiteboardctl delete-card CARD REVISION\n"
        "  whiteboardctl delete-cards REVISION < FILE\n"
        "  whiteboardctl proposal ID\n"
        "  whiteboardctl propose note|markdown|code X Y W H < FILE\n"
        "  whiteboardctl create-cards [REVISION] < FILE\n"
        "  whiteboardctl replace-card CARD REVISION W H < FILE\n";
}

static std::int64_t monotonic_milliseconds() {
    timespec value{};

    if (::clock_gettime(CLOCK_MONOTONIC, &value) != 0) {
        return -1;
    }

    return
        static_cast<std::int64_t>(value.tv_sec) * 1000 +
        value.tv_nsec / 1'000'000;
}

static int wait_for_socket(
    int fd,
    short events,
    std::int64_t deadline
) {
    for (;;) {
        const std::int64_t now = monotonic_milliseconds();

        if (now < 0 || now >= deadline) {
            errno = ETIMEDOUT;
            return -1;
        }

        const std::int64_t remaining = deadline - now;
        pollfd descriptor{
            .fd = fd,
            .events = events,
            .revents = 0,
        };
        const int ready = ::poll(
            &descriptor,
            1,
            static_cast<int>(std::min<std::int64_t>(
                remaining,
                std::numeric_limits<int>::max()
            ))
        );

        if (ready > 0) {
            return descriptor.revents;
        }

        if (ready == 0) {
            errno = ETIMEDOUT;
            return -1;
        }

        if (errno != EINTR) {
            return -1;
        }
    }
}

static bool write_all(
    int fd,
    std::string_view bytes,
    std::int64_t deadline
) {
    while (!bytes.empty()) {
        const ssize_t count = ::send(
            fd,
            bytes.data(),
            bytes.size(),
            whiteboard::platform::no_signal_send_flags()
        );

        if (count < 0) {
            if (errno == EINTR) {
                continue;
            }

            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                if (wait_for_socket(fd, POLLOUT, deadline) >= 0) {
                    continue;
                }
            }
            return false;
        }

        bytes.remove_prefix(static_cast<std::size_t>(count));
    }

    return true;
}

static int connect_agent(
    const std::string& path,
    std::int64_t deadline
) {
    whiteboard::platform::LocalSocketAddress address;

    if (!whiteboard::platform::make_local_socket_address(path, address)) {
        return -1;
    }

    const int fd = whiteboard::platform::open_local_stream();

    if (fd < 0) {
        return -1;
    }

    if (::connect(
            fd,
            reinterpret_cast<const sockaddr*>(&address.value),
            address.size
        ) != 0) {
        if (errno != EINPROGRESS) {
            const int connect_error = errno;
            ::close(fd);
            errno = connect_error;
            return -1;
        }

        if (wait_for_socket(fd, POLLOUT, deadline) < 0) {
            const int connect_error = errno;
            ::close(fd);
            errno = connect_error;
            return -1;
        }

        int connect_error = 0;
        socklen_t error_size = sizeof(connect_error);

        if (
            ::getsockopt(
                fd,
                SOL_SOCKET,
                SO_ERROR,
                &connect_error,
                &error_size
            ) != 0 ||
            connect_error != 0
        ) {
            if (connect_error != 0) {
                errno = connect_error;
            }
            const int saved_error = errno;
            ::close(fd);
            errno = saved_error;
            return -1;
        }
    }

    return fd;
}

static std::string uppercase_kind(std::string_view kind) {
    if (kind == "note") {
        return "NOTE";
    }

    if (kind == "markdown") {
        return "MARKDOWN";
    }

    if (kind == "code") {
        return "CODE";
    }

    return {};
}

static bool read_request_body(
    std::string& body,
    std::string_view name
) {
    body.clear();
    body.reserve(std::min<std::size_t>(kAgentTextLimit, 64 * 1024));
    char bytes[16 * 1024];

    for (;;) {
        const std::size_t remaining =
            kAgentTextLimit + 1 - body.size();
        const std::size_t requested = std::min<std::size_t>(
            sizeof(bytes),
            remaining
        );
        std::cin.read(
            bytes,
            static_cast<std::streamsize>(requested)
        );
        const std::streamsize count = std::cin.gcount();

        if (count > 0) {
            if (
                static_cast<std::size_t>(count) >
                kAgentTextLimit - body.size()
            ) {
                std::cerr << "whiteboardctl: " << name
                          << " too large\n";
                return false;
            }

            body.append(bytes, static_cast<std::size_t>(count));
        }

        if (std::cin.eof()) {
            break;
        }

        if (!std::cin) {
            std::cerr << "whiteboardctl: cannot read " << name << '\n';
            return false;
        }
    }

    return true;
}

static int agent_timeout_milliseconds() {
    const char* raw = std::getenv("WHITEBOARDCTL_TIMEOUT_MS");

    if (raw == nullptr || *raw == '\0') {
        return kAgentDefaultTimeoutMilliseconds;
    }

    int value = 0;
    const std::string_view text{raw};
    const auto parsed = std::from_chars(
        text.data(),
        text.data() + text.size(),
        value
    );

    return
        parsed.ec == std::errc{} &&
        parsed.ptr == text.data() + text.size() &&
        value >= 10 && value <= 600'000
            ? value
            : kAgentDefaultTimeoutMilliseconds;
}

static bool perform_request(
    std::string_view request,
    std::string& response
) {
    const std::string path = agent_socket_path();
    const std::int64_t now = monotonic_milliseconds();

    if (now < 0) {
        std::cerr << "whiteboardctl: monotonic clock unavailable\n";
        return false;
    }

    const std::int64_t deadline =
        now + agent_timeout_milliseconds();
    const int fd = connect_agent(path, deadline);

    if (fd < 0) {
        std::cerr << "whiteboardctl: cannot connect " << path << ": "
                  << std::strerror(errno) << '\n';
        return false;
    }

    if (!write_all(fd, request, deadline)) {
        std::cerr << "whiteboardctl: write failed: "
                  << std::strerror(errno) << '\n';
        ::close(fd);
        return false;
    }

    ::shutdown(fd, SHUT_WR);
    char bytes[16 * 1024];
    response.clear();

    for (;;) {
        if (wait_for_socket(fd, POLLIN, deadline) < 0) {
            std::cerr << "whiteboardctl: read failed: "
                      << std::strerror(errno) << '\n';
            ::close(fd);
            return false;
        }

        const ssize_t count = ::recv(fd, bytes, sizeof(bytes), 0);

        if (count == 0) {
            break;
        }

        if (count < 0) {
            if (
                errno == EINTR ||
                errno == EAGAIN ||
                errno == EWOULDBLOCK
            ) {
                continue;
            }

            std::cerr << "whiteboardctl: read failed\n";
            ::close(fd);
            return false;
        }

        if (
            static_cast<std::size_t>(count) >
            kAgentResponseLimit - response.size()
        ) {
            std::cerr << "whiteboardctl: response too large\n";
            ::close(fd);
            return false;
        }

        response.append(bytes, static_cast<std::size_t>(count));
    }

    ::close(fd);
    return true;
}

static bool make_request(
    int argc,
    char** argv,
    std::string& request,
    std::string_view& body_kind
) {
    const std::string_view command = argv[1];

    if (command == "status" && argc == 2) {
        request = "STATUS\n";
    } else if (command == "view" && argc == 2) {
        request = "VIEW\n";
    } else if (command == "screen-text" && argc == 2) {
        request = "SCREEN_TEXT\n";
        body_kind = "SCREEN_TEXT";
    } else if (
        command == "screen-png" &&
        (argc == 2 || argc == 3)
    ) {
        request = "SCREEN_PNG";

        if (argc == 3) {
            request.push_back(' ');
            request.append(argv[2]);
        }

        request.push_back('\n');
        body_kind = "SCREEN_PNG";
    } else if (
        command == "board-png" &&
        argc >= 2 &&
        argc <= 5
    ) {
        request = "BOARD_PNG";

        if (argc >= 3) {
            request.push_back(' ');
            request.append(argv[2]);
        }

        if (argc >= 4) {
            const std::string_view label = argv[3];

            if (label == "name") {
                request.append(" NAME");
            } else if (label == "format") {
                request.append(" FORMAT");
            } else if (label == "id") {
                request.append(" ID");
            } else {
                return false;
            }
        }

        if (argc == 5) {
            if (std::string_view{argv[4]} != "viewport") {
                return false;
            }

            request.append(" VIEWPORT");
        }

        request.push_back('\n');
        body_kind = "BOARD_PNG";
    } else if (command == "get" && argc == 3) {
        request = "GET ";
        request.append(argv[2]);
        request.push_back('\n');
    } else if (command == "edges" && argc == 3) {
        request = "EDGES ";
        request.append(argv[2]);
        request.push_back('\n');
    } else if (
        command == "connect" &&
        (argc == 4 || argc == 5)
    ) {
        request = "CONNECT ";
        request.append(argv[2]);
        request.push_back(' ');
        request.append(argv[3]);

        if (argc == 5) {
            request.push_back(' ');
            request.append(argv[4]);
        }

        request.push_back('\n');
    } else if (command == "delete-card" && argc == 4) {
        request = "DELETE_CARD ";
        request.append(argv[2]);
        request.push_back(' ');
        request.append(argv[3]);
        request.push_back('\n');
    } else if (command == "delete-cards" && argc == 3) {
        std::string body;

        if (!read_request_body(body, "delete batch")) {
            return false;
        }

        request = "DELETE_CARDS ";
        request.append(argv[2]);
        request.push_back(' ');
        append_decimal(request, body.size());
        request.push_back('\n');
        request.append(body);
    } else if (command == "proposal" && argc == 3) {
        request = "PROPOSAL ";
        request.append(argv[2]);
        request.push_back('\n');
    } else if (
        command == "query" &&
        (argc == 6 || argc == 7)
    ) {
        request = "QUERY ";

        for (int i = 2; i < 6; ++i) {
            if (i != 2) {
                request.push_back(' ');
            }
            request.append(argv[i]);
        }

        request.push_back(' ');
        request.append(argc == 7 ? argv[6] : "64");
        request.push_back('\n');
    } else if (command == "propose" && argc == 7) {
        const std::string kind = uppercase_kind(argv[2]);

        if (kind.empty()) {
            return false;
        }

        std::string body;

        if (!read_request_body(body, "proposal text")) {
            return false;
        }

        request = "PROPOSE ";
        request.append(kind);

        for (int i = 3; i < 7; ++i) {
            request.push_back(' ');
            request.append(argv[i]);
        }

        request.push_back(' ');
        append_decimal(request, body.size());
        request.push_back('\n');
        request.append(body);
    } else if (
        command == "create-cards" &&
        (argc == 2 || argc == 3)
    ) {
        std::string body;

        if (!read_request_body(body, "card batch")) {
            return false;
        }

        request = "CREATE_CARDS ";

        if (argc == 3) {
            request.append(argv[2]);
            request.push_back(' ');
        }

        append_decimal(request, body.size());
        request.push_back('\n');
        request.append(body);
    } else if (command == "replace-card" && argc == 6) {
        std::string body;

        if (!read_request_body(body, "replacement text")) {
            return false;
        }

        request = "REPLACE_CARD";

        for (int i = 2; i < 6; ++i) {
            request.push_back(' ');
            request.append(argv[i]);
        }

        request.push_back(' ');
        append_decimal(request, body.size());
        request.push_back('\n');
        request.append(body);
    } else {
        return false;
    }

    return true;
}

static bool write_response_body(
    std::string_view response,
    std::string_view kind
) {
    if (response.starts_with("ERR ")) {
        std::cerr.write(response.data(), response.size());
        return false;
    }

    const std::size_t newline = response.find('\n');

    if (newline == std::string_view::npos) {
        std::cerr << "whiteboardctl: invalid screenshot response\n";
        return false;
    }

    const std::string_view header = response.substr(0, newline);
    std::array<std::string_view, 6> words{};
    std::size_t count = 0;

    for (std::size_t begin = 0; begin < header.size();) {
        if (count == words.size()) {
            std::cerr << "whiteboardctl: invalid screenshot response\n";
            return false;
        }

        const std::size_t end = header.find(' ', begin);
        words[count++] = header.substr(
            begin,
            end == std::string_view::npos
                ? header.size() - begin
                : end - begin
        );

        if (end == std::string_view::npos) {
            break;
        }

        begin = end + 1;
    }

    if (
        count != words.size() ||
        words[0] != "OK" ||
        words[2] != kind
    ) {
        std::cerr << "whiteboardctl: invalid screenshot response\n";
        return false;
    }

    std::size_t body_size = 0;
    const auto parsed = std::from_chars(
        words[5].data(),
        words[5].data() + words[5].size(),
        body_size
    );
    const std::string_view body = response.substr(newline + 1);

    if (
        parsed.ec != std::errc{} ||
        parsed.ptr != words[5].data() + words[5].size() ||
        body.size() != body_size
    ) {
        std::cerr << "whiteboardctl: invalid screenshot response\n";
        return false;
    }

    std::cout.write(body.data(), body.size());

    if (!std::cout) {
        std::cerr << "whiteboardctl: output failed\n";
        return false;
    }

    return true;
}

struct SnapshotPageHeader {
    std::uint64_t revision = 0;
    std::uint64_t next_card = 0;
    std::uint64_t next_edge = 0;
    std::uint64_t next_glyph = 0;
    std::size_t body_size = 0;
    bool done = false;
};

template<class Unsigned>
static bool parse_canonical_unsigned(
    std::string_view text,
    Unsigned& value
) {
    if (text.empty()) {
        return false;
    }

    const auto parsed = std::from_chars(
        text.data(),
        text.data() + text.size(),
        value
    );

    if (
        parsed.ec != std::errc{} ||
        parsed.ptr != text.data() + text.size()
    ) {
        return false;
    }

    std::string canonical;
    append_decimal(canonical, value);
    return canonical == text;
}

static bool parse_snapshot_page(
    std::string_view response,
    SnapshotPageHeader& result,
    std::string_view& body
) {
    const std::size_t newline = response.find('\n');

    if (newline == std::string_view::npos) {
        return false;
    }

    const std::string_view header = response.substr(0, newline);
    std::array<std::string_view, 9> words{};
    std::size_t count = 0;
    std::size_t begin = 0;

    while (begin < header.size()) {
        if (count == words.size()) {
            return false;
        }

        const std::size_t end = header.find(' ', begin);
        words[count++] = header.substr(
            begin,
            end == std::string_view::npos
                ? header.size() - begin
                : end - begin
        );

        if (words[count - 1].empty()) {
            return false;
        }

        if (end == std::string_view::npos) {
            break;
        }

        begin = end + 1;
    }

    std::uint32_t version = 0;
    if (
        count != words.size() ||
        words[0] != "OK" ||
        words[2] != "SNAPSHOT" ||
        !parse_canonical_unsigned(words[3], version) ||
        version != kAgentProtocolVersion ||
        !parse_canonical_unsigned(words[1], result.revision) ||
        !parse_canonical_unsigned(words[4], result.next_card) ||
        !parse_canonical_unsigned(words[5], result.next_edge) ||
        !parse_canonical_unsigned(words[6], result.next_glyph) ||
        !parse_canonical_unsigned(words[8], result.body_size) ||
        (words[7] != "0" && words[7] != "1")
    ) {
        return false;
    }

    result.done = words[7] == "1";
    body = response.substr(newline + 1);
    return body.size() == result.body_size;
}

static bool write_snapshot_file(const std::string& output_path) {
    AtomicFileWriter writer(output_path);

    if (!writer.good()) {
        std::cerr << "whiteboardctl: cannot create snapshot output: "
                  << writer.error() << '\n';
        return false;
    }

    writer.stream().write(
        whiteboard::verification::kCanonicalSnapshotMagic,
        sizeof(whiteboard::verification::kCanonicalSnapshotMagic) - 1
    );

    std::uint64_t expected_revision = 0;
    bool revision_set = false;
    std::uint64_t card_cursor = 0;
    std::uint64_t edge_cursor = 0;
    std::uint64_t glyph_cursor = 0;
    constexpr std::size_t kMaximumSnapshotPages = 1'000'000;

    for (std::size_t page_number = 0;
         page_number < kMaximumSnapshotPages;
         ++page_number) {
        std::string request = "SNAPSHOT ";

        if (revision_set) {
            append_decimal(request, expected_revision);
        } else {
            request.push_back('-');
        }

        request.push_back(' ');
        append_decimal(request, card_cursor);
        request.push_back(' ');
        append_decimal(request, edge_cursor);
        request.push_back(' ');
        append_decimal(request, glyph_cursor);
        request.push_back('\n');

        std::string response;

        if (!perform_request(request, response)) {
            return false;
        }

        const AgentResponseStatus status = agent_response_status(response);

        if (status == AgentResponseStatus::Error) {
            std::cerr.write(response.data(), response.size());
            return false;
        }

        if (status != AgentResponseStatus::Ok) {
            std::cerr << "whiteboardctl: invalid snapshot response\n";
            return false;
        }

        SnapshotPageHeader header;
        std::string_view body;

        if (!parse_snapshot_page(response, header, body)) {
            std::cerr << "whiteboardctl: invalid snapshot response\n";
            return false;
        }

        if (revision_set && header.revision != expected_revision) {
            std::cerr << "whiteboardctl: snapshot revision changed\n";
            return false;
        }

        if (!revision_set) {
            expected_revision = header.revision;
            revision_set = true;

            if (!body.starts_with("META ")) {
                std::cerr << "whiteboardctl: snapshot missing metadata\n";
                return false;
            }
        }

        if (
            header.next_card < card_cursor ||
            header.next_edge < edge_cursor ||
            header.next_glyph < glyph_cursor ||
            (!header.done &&
             header.next_card == card_cursor &&
             header.next_edge == edge_cursor &&
             header.next_glyph == glyph_cursor)
        ) {
            std::cerr << "whiteboardctl: invalid snapshot cursor progress\n";
            return false;
        }

        writer.stream().write(
            body.data(),
            static_cast<std::streamsize>(body.size())
        );

        if (!writer.stream()) {
            std::cerr << "whiteboardctl: snapshot output failed\n";
            return false;
        }

        card_cursor = header.next_card;
        edge_cursor = header.next_edge;
        glyph_cursor = header.next_glyph;

        if (header.done) {
            writer.stream().write("END\n", 4);

            if (!writer.commit()) {
                std::cerr << "whiteboardctl: cannot commit snapshot: "
                          << writer.error() << '\n';
                return false;
            }

            return true;
        }
    }

    std::cerr << "whiteboardctl: too many snapshot pages\n";
    return false;
}

int main(int argc, char** argv) {
    if (argc < 2) {
        usage();
        return EXIT_FAILURE;
    }

    if (
        std::string_view{argv[1]} == "snapshot" &&
        argc == 4 &&
        std::string_view{argv[2]} == "--output" &&
        !std::string_view{argv[3]}.empty()
    ) {
        return write_snapshot_file(argv[3])
            ? EXIT_SUCCESS
            : EXIT_FAILURE;
    }

    std::string request;
    std::string_view body_kind;

    if (!make_request(argc, argv, request, body_kind)) {
        usage();
        return EXIT_FAILURE;
    }

    std::string response;

    if (!perform_request(request, response)) {
        return EXIT_FAILURE;
    }

    const AgentResponseStatus status = agent_response_status(response);

    if (status == AgentResponseStatus::Error) {
        std::cerr.write(response.data(), response.size());
        return EXIT_FAILURE;
    }

    if (status != AgentResponseStatus::Ok) {
        std::cerr << "whiteboardctl: invalid response\n";
        return EXIT_FAILURE;
    }

    if (!body_kind.empty() && !write_response_body(response, body_kind)) {
        return EXIT_FAILURE;
    }

    if (body_kind.empty()) {
        std::cout.write(response.data(), response.size());

        if (!std::cout) {
            std::cerr << "whiteboardctl: output failed\n";
            return EXIT_FAILURE;
        }
    }

    return EXIT_SUCCESS;
}
