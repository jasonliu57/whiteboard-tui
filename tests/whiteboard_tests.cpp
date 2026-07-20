#include "standalone_fixture.hpp"
#include "../src/platform/native/app_io.hpp"
#include <fstream>
#include "storage/native.hpp"
#include "../src/agent_server.hpp"
#include "../src/app.hpp"
#include "../src/platform/posix_fd.hpp"
#include "../src/render/thumbnail.hpp"
#include "../src/render/overview.hpp"
#include "../src/storage/atomic_file.hpp"
#include "../src/storage/card_content.hpp"
#include "../src/storage/project.hpp"
#include "../src/tui/terminal.hpp"
#include "../src/verification/canonical_snapshot.hpp"

#include <cerrno>
#include <clocale>
#include <algorithm>
#include <array>
#include <cstdlib>
#include <filesystem>
#include <fcntl.h>
#include <iostream>
#include <poll.h>
#include <span>
#include <sstream>
#include <streambuf>
#include <string>
#include <string_view>
#include <sys/socket.h>
#include <sys/stat.h>
#include <unistd.h>

namespace {

int failures = 0;

struct RequirementFailure {};

#define CHECK(condition) do {                                              \
    if (!(condition)) {                                                    \
        std::cerr << __FILE__ << ':' << __LINE__                           \
                  << ": CHECK failed: " #condition << '\n';               \
        ++failures;                                                        \
    }                                                                      \
} while (false)

#define REQUIRE(condition) do {                                            \
    if (!(condition)) {                                                    \
        std::cerr << __FILE__ << ':' << __LINE__                           \
                  << ": REQUIRE failed: " #condition << '\n';             \
        ++failures;                                                        \
        throw RequirementFailure{};                                        \
    }                                                                      \
} while (false)

class FailingOutputBuffer final : public std::streambuf {
public:
    explicit FailingOutputBuffer(std::size_t limit) : remaining_(limit) {}

protected:
    std::streamsize xsputn(
        const char*,
        std::streamsize count
    ) override {
        const auto accepted = static_cast<std::streamsize>(
            std::min<std::size_t>(remaining_, count)
        );
        remaining_ -= static_cast<std::size_t>(accepted);
        return accepted;
    }

    int_type overflow(int_type character) override {
        if (traits_type::eq_int_type(character, traits_type::eof())) {
            return traits_type::not_eof(character);
        }

        if (remaining_ == 0) {
            return traits_type::eof();
        }

        --remaining_;
        return character;
    }

private:
    std::size_t remaining_;
};

class TemporaryDirectory {
public:
    TemporaryDirectory() {
        std::string pattern = "/tmp/whiteboard-tests-XXXXXX";
        pattern.push_back('\0');
        char* created = ::mkdtemp(pattern.data());

        if (created == nullptr) {
            std::perror("mkdtemp");
            std::exit(2);
        }

        path_ = created;
    }

    TemporaryDirectory(const TemporaryDirectory&) = delete;
    TemporaryDirectory& operator=(const TemporaryDirectory&) = delete;

    ~TemporaryDirectory() {
        std::error_code error;
        std::filesystem::remove_all(path_, error);
    }

    std::string file(std::string_view name) const {
        return path_ + '/' + std::string{name};
    }

    const std::string& path() const noexcept {
        return path_;
    }

private:
    std::string path_;
};

void create_regular_file(const std::string& path) {
    const int descriptor = ::open(
        path.c_str(),
        O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC,
        S_IRUSR | S_IWUSR
    );
    CHECK(descriptor >= 0);

    if (descriptor >= 0) {
        CHECK(::write(descriptor, "keep", 4) == 4);
        CHECK(::close(descriptor) == 0);
    }
}

std::string read_file(const std::string& path) {
    std::ifstream input(path, std::ios::binary);
    return {
        std::istreambuf_iterator<char>{input},
        std::istreambuf_iterator<char>{},
    };
}

void make_stale_socket(const std::string& path) {
    const int descriptor = whiteboard::platform::open_local_stream();
    CHECK(descriptor >= 0);

    whiteboard::platform::LocalSocketAddress address;
    CHECK(whiteboard::platform::make_local_socket_address(path, address));
    CHECK(::bind(
        descriptor,
        reinterpret_cast<const sockaddr*>(&address.value),
        address.size
    ) == 0);
    CHECK(::close(descriptor) == 0);
}

int connect_unix_socket(const std::string& path) {
    const int descriptor = whiteboard::platform::open_local_stream();
    REQUIRE(descriptor >= 0);
    whiteboard::platform::LocalSocketAddress address;
    REQUIRE(whiteboard::platform::make_local_socket_address(path, address));
    const int result = ::connect(
        descriptor,
        reinterpret_cast<const sockaddr*>(&address.value),
        address.size
    );
    REQUIRE(result == 0 || errno == EINPROGRESS);

    if (result != 0 && errno == EINPROGRESS) {
        pollfd event{descriptor, POLLOUT, 0};
        REQUIRE(::poll(&event, 1, 1000) == 1);
        int connect_error = 0;
        socklen_t error_size = sizeof(connect_error);
        CHECK(::getsockopt(
            descriptor,
            SOL_SOCKET,
            SO_ERROR,
            &connect_error,
            &error_size
        ) == 0);
        REQUIRE(connect_error == 0);
    }

    return descriptor;
}

void test_core_board_slots() {
    Board board;
    Card first;
    first.pos = {2, 3};
    const CardId first_id = board.add(std::move(first));
    REQUIRE(first_id == 0);
    Card removed = board.take(first_id);

    Card second;
    const CardId second_id = board.add(std::move(second));
    REQUIRE(second_id == 1);
    CHECK(board.find(first_id) == nullptr);
    board.restore(first_id, std::move(removed));
    CHECK((board.get(first_id).pos == Pos{2, 3}));
    CHECK(board.live_cards == 2);
}

void test_core_format_registry() {
    const CardFormats formats = make_card_formats();
    const std::array<GeneratedCardFormatContract, 7> contracts{
        kCardFormatNote,
        kCardFormatMarkdown,
        kCardFormatCode,
        kCardFormatTodo,
        kCardFormatCsv,
        kCardFormatFolder,
        kCardFormatTextArt,
    };
    REQUIRE(formats.size() == contracts.size());
    for (std::size_t index = 0; index < contracts.size(); ++index) {
        const CardFormat& format = formats[index];
        const GeneratedCardFormatContract& contract = contracts[index];
        CHECK((format.minimum_layout == Extent{
            contract.minimum_width,
            contract.minimum_height,
        }));
        CHECK((format.maximum_layout == Extent{
            contract.maximum_width,
            contract.maximum_height,
        }));
        CHECK(format.create_empty != nullptr);

        const std::array<Extent, 3> extents{
            format.minimum_layout,
            Extent{
                (format.minimum_layout.width +
                 format.maximum_layout.width) / 2,
                (format.minimum_layout.height +
                 format.maximum_layout.height) / 2,
            },
            format.maximum_layout,
        };

        for (const Extent extent : extents) {
            Card card;
            const Pos position{
                static_cast<i64>(index) * 200,
                -static_cast<i64>(index) * 200,
            };
            REQUIRE(create_registered_card(
                formats,
                static_cast<StaticFormatId>(index),
                position,
                extent,
                card
            ));
            CHECK(card.pos == position);
            CHECK(card.static_format == static_cast<StaticFormatId>(index));
            CHECK(card_save_format(card) == static_cast<SaveFormat>(contract.save_format));
            CHECK(card_data_matches(format.data_kind, card.data));
            CHECK(format.measure(card.data) == extent);
        }
    }

    Card rejected;
    CHECK(!create_registered_card(
        formats,
        static_cast<StaticFormatId>(formats.size()),
        {},
        formats[0].minimum_layout,
        rejected
    ));
    CHECK(!create_registered_card(
        formats,
        kPlainTextNoteStaticFormatId,
        {},
        {formats[0].minimum_layout.width - 1,
         formats[0].minimum_layout.height},
        rejected
    ));
    CHECK(!create_registered_card(
        formats,
        kPlainTextNoteStaticFormatId,
        {std::numeric_limits<i64>::max(), 0},
        formats[0].minimum_layout,
        rejected
    ));
}

void test_core_batch_parser() {
    const CardFormats formats = make_card_formats();
    std::vector<Card> parsed_cards;
    u32 invalid_line = 0;
    REQUIRE(build_registered_card_batch(
        formats,
        "note 0 0 12 5\n"
        "markdown 20 0 16 6\n"
        "code 40 0 20 7\n"
        "todo 65 0 12 5\n"
        "csv 85 0 14 5\n"
        "folder 105 0 16 5\n"
        "text-art 130 0 1 1\n",
        parsed_cards,
        invalid_line
    ) == RegisteredCardBatchResult::Success);
    CHECK(parsed_cards.size() == formats.size());
    CHECK(invalid_line == 0);

    std::vector<Card> preserved_batch;
    preserved_batch.push_back(make_plain_text_note({0, 0}));
    CHECK(build_registered_card_batch(
        formats,
        "note 0 0 12 5\n\nunknown 0 0 1 1\n",
        preserved_batch,
        invalid_line
    ) == RegisteredCardBatchResult::InvalidLine);
    CHECK(invalid_line == 3);
    CHECK(preserved_batch.size() == 1);
    CHECK(build_registered_card_batch(
        formats,
        " \t\r\n",
        preserved_batch,
        invalid_line
    ) == RegisteredCardBatchResult::Empty);
    CHECK(preserved_batch.size() == 1);
}

void test_core_batch_mutation() {
    const CardFormats formats = make_card_formats();
    App registry_app(80, 24);
    std::vector<Card> registered_cards;

    for (StaticFormatId id = 0; id < formats.size(); ++id) {
        Card card;
        CHECK(create_registered_card(
            formats,
            id,
            {static_cast<i64>(id) * 200, 0},
            formats[id].minimum_layout,
            card
        ));
        registered_cards.push_back(std::move(card));
    }

    REQUIRE(registry_app.add_cards(std::move(registered_cards)) == 0);
    CHECK(registry_app.board.live_cards == formats.size());
    CHECK(registry_app.history.entries.size() == 1);
    CHECK(registry_app.history.cursor == 1);
    CHECK(registry_app.revision == 1);

    for (StaticFormatId id = 0; id < formats.size(); ++id) {
        CHECK(registry_app.board.get(id).static_format == id);
    }

    CHECK(registry_app.undo());
    CHECK(registry_app.board.live_cards == 0);
    CHECK(registry_app.redo());
    CHECK(registry_app.board.live_cards == formats.size());

    App rejected_batch_app(80, 24);
    std::vector<Card> rejected_batch;

    for (StaticFormatId id = 0; id < formats.size(); ++id) {
        Card card;
        CHECK(create_registered_card(
            formats,
            id,
            {static_cast<i64>(id) * 200, 0},
            formats[id].minimum_layout,
            card
        ));
        rejected_batch.push_back(std::move(card));
    }

    Card invalid_tail;
    invalid_tail.static_format = static_cast<StaticFormatId>(formats.size());
    rejected_batch.push_back(std::move(invalid_tail));
    CHECK(rejected_batch_app.add_cards(std::move(rejected_batch)) == kNoCard);
    CHECK(rejected_batch_app.board.cards.empty());
    CHECK(rejected_batch_app.history.entries.empty());
    CHECK(rejected_batch_app.revision == 0);
}

void test_storage_codec() {
    constexpr std::string_view crc32_vector = "123456789";
    CHECK(project_crc32(crc32_vector.data(), crc32_vector.size()) ==
          0xCBF43926U);

    std::stringstream integer_stream(
        std::ios::in | std::ios::out | std::ios::binary
    );
    write_value(integer_stream, u8{0xA5});
    write_value(integer_stream, u16{0x1234});
    write_value(integer_stream, u32{0x89ABCDEF});
    write_value(integer_stream, UINT64_C(0x0123456789ABCDEF));
    const std::string integer_bytes = integer_stream.str();
    CHECK(integer_bytes == std::string(
        "\xA5\x34\x12\xEF\xCD\xAB\x89"
        "\xEF\xCD\xAB\x89\x67\x45\x23\x01",
        15
    ));
    integer_stream.seekg(0);
    ProjectReader integer_reader(integer_stream, integer_bytes.size());
    CHECK(read_value<u8>(integer_reader) == u8{0xA5});
    CHECK(read_value<u16>(integer_reader) == u16{0x1234});
    CHECK(read_value<u32>(integer_reader) == u32{0x89ABCDEF});
    CHECK(read_value<u64>(integer_reader) ==
          UINT64_C(0x0123456789ABCDEF));
    CHECK(static_cast<bool>(integer_reader));

    std::stringstream stream(
        std::ios::in | std::ios::out | std::ios::binary
    );
    write_string(stream, std::string_view{"alpha\0beta", 10});
    stream.seekg(0);
    ProjectReader reader(stream, stream.str().size());
    CHECK(read_string(reader) == std::string("alpha\0beta", 10));
    CHECK(static_cast<bool>(reader));

    std::stringstream budget_stream(
        std::ios::in | std::ios::out | std::ios::binary
    );
    write_string(budget_stream, "four");
    const std::string budget_bytes = budget_stream.str();
    budget_stream.seekg(0);
    ProjectReader budget_reader(
        budget_stream,
        budget_bytes.size(),
        3
    );
    CHECK(read_string(budget_reader).empty());
    CHECK(!budget_reader);

    // The native writer must enforce the combined file budget, even when
    // each individual section fits its own limit.
    std::ostringstream section_stream(std::ios::binary);
    std::string section_buffer;
    u64 remaining_bytes = 20;
    const auto write_empty_slots = [](std::ostream& output) {
        write_value(output, u32{0});
    };
    CHECK(write_project_section(
        section_stream, kCardsSection, section_buffer,
        write_empty_slots, &remaining_bytes
    ));
    CHECK(remaining_bytes == 0);
    const std::string first_section = section_stream.str();
    CHECK(!write_project_section(
        section_stream, kEdgesSection, section_buffer,
        write_empty_slots, &remaining_bytes
    ));
    CHECK(section_stream.str() == first_section);
}

void test_storage_atomic_writer() {
    TemporaryDirectory temporary;
    const std::string target = temporary.file("board.tiwb");
    create_regular_file(target);

    {
        AtomicFileWriter writer(target);
        REQUIRE(writer.good());
        writer.stream() << "replacement";
        CHECK(writer.commit());
    }

    CHECK(read_file(target) == "replacement");

    for (const auto& [fault, expected_error] : {
             std::pair{AtomicFileFault::NoSpace, ENOSPC},
             std::pair{AtomicFileFault::Close, EIO},
             std::pair{AtomicFileFault::Rename, EIO},
         }) {
        AtomicFileWriter writer(target, fault);
        REQUIRE(writer.good());
        writer.stream() << "must not replace";
        CHECK(!writer.commit());
        CHECK(writer.error_number() == expected_error);
        CHECK(read_file(target) == "replacement");
    }

    {
        AtomicFileWriter writer(target);
        REQUIRE(writer.good());
        writer.stream() << "not committed";
    }

    CHECK(read_file(target) == "replacement");
}

void test_storage_project_validation() {
    TemporaryDirectory temporary;
    Board empty_board;
    GlyphLayer empty_glyphs;
    const CardFormats formats = make_card_formats();
    const std::string valid_project = temporary.file("valid.tiwb");
    REQUIRE(whiteboard::io::save_project(
        valid_project,
        empty_board,
        empty_glyphs
    ));

    Board loaded_board;
    CardSpatial loaded_spatial;
    GlyphLayer loaded_glyphs;
    CHECK(whiteboard::io::load_project(
        valid_project,
        loaded_board,
        loaded_spatial,
        loaded_glyphs,
        formats
    ));

    const std::string unsupported_project = temporary.file("unsupported-format.tiwb");
    {
        std::ofstream output(unsupported_project, std::ios::binary);
        write_value(output, kBoardMagic);
        write_value(output, std::numeric_limits<u32>::max());
    }
    CHECK(!whiteboard::io::load_project(
        unsupported_project,
        loaded_board,
        loaded_spatial,
        loaded_glyphs,
        formats
    ));

    const std::string bad_checksum = temporary.file("bad-checksum.tiwb");
    {
        std::ifstream input(valid_project, std::ios::binary);
        std::string bytes(
            std::istreambuf_iterator<char>{input},
            std::istreambuf_iterator<char>{}
        );
        CHECK(bytes.size() > 24);
        bytes[24] ^= 0x01;
        std::ofstream output(bad_checksum, std::ios::binary);
        output.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    }
    CHECK(!whiteboard::io::load_project(
        bad_checksum,
        loaded_board,
        loaded_spatial,
        loaded_glyphs,
        formats
    ));

    const std::string truncated = temporary.file("truncated.tiwb");
    {
        std::ifstream input(valid_project, std::ios::binary);
        std::string bytes(
            std::istreambuf_iterator<char>{input},
            std::istreambuf_iterator<char>{}
        );
        CHECK(!bytes.empty());
        bytes.pop_back();
        std::ofstream output(truncated, std::ios::binary);
        output.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    }
    CHECK(!whiteboard::io::load_project(
        truncated,
        loaded_board,
        loaded_spatial,
        loaded_glyphs,
        formats
    ));

    const std::string hostile_count = temporary.file("hostile-count.tiwb");
    {
        std::ofstream output(hostile_count, std::ios::binary);
        write_value(output, kBoardMagic);
        write_value(output, kBoardFormatId);
        write_value(output, std::numeric_limits<u32>::max());
    }
    CHECK(!whiteboard::io::load_project(
        hostile_count,
        loaded_board,
        loaded_spatial,
        loaded_glyphs,
        formats
    ));

    const std::string hostile_string = temporary.file("hostile-string.tiwb");
    {
        std::ofstream output(hostile_string, std::ios::binary);
        write_value(output, kBoardMagic);
        write_value(output, kBoardFormatId);
        write_value(output, kBoardSectionCount);
        std::string buffer;
        CHECK(write_project_section(
            output,
            kCardsSection,
            buffer,
            [](std::ostream& section) {
                write_value(section, u32{1});
                write_value(section, u8{1});
                write_value(section, i64{0});
                write_value(section, i64{0});
                write_value(section, StaticFormatId{0});
                write_extent(section, {12, 5});
                write_value(section, kPlainTextLanguageId);
                write_value(section, u32{0});
                write_value(section, u32{1});
                write_value(
                    section,
                    std::numeric_limits<u32>::max()
                );
            }
        ));
        CHECK(write_project_section(
            output,
            kEdgesSection,
            buffer,
            [](std::ostream& section) {
                write_value(section, u32{0});
            }
        ));
        CHECK(write_project_section(
            output,
            kGlyphsSection,
            buffer,
            [](std::ostream& section) {
                write_value(section, u32{0});
            }
        ));
    }
    CHECK(!whiteboard::io::load_project(
        hostile_string,
        loaded_board,
        loaded_spatial,
        loaded_glyphs,
        formats
    ));

    const std::string hostile_lines(
        kMaximumContentTextLines,
        '\n'
    );
    TextCardData text_preserved;
    text_preserved.lines = {"keep"};
    CardData preserved_text = std::move(text_preserved);
    CHECK(!whiteboard::io::read_card_content(
        hostile_lines,
        SaveFormat::PlainText,
        preserved_text
    ));
    CHECK(std::get<TextCardData>(preserved_text).lines ==
          TextLines{"keep"});

    TodoCardData todo_preserved;
    TodoItem preserved_item{"keep", true};
    preserved_item.style = {3, 0, AttrBold};
    todo_preserved.items = {std::move(preserved_item)};
    CardData preserved_todo = std::move(todo_preserved);
    CHECK(!whiteboard::io::read_card_content(
        hostile_lines,
        SaveFormat::TodoText,
        preserved_todo
    ));
    CHECK(std::get<TodoCardData>(preserved_todo).items.size() == 1);
    CHECK(std::get<TodoCardData>(preserved_todo).items[0].text == "keep");
    CHECK(std::get<TodoCardData>(preserved_todo).items[0].done);
}

void test_agent_socket_flags() {
    const int configured = whiteboard::platform::open_local_stream();
    CHECK(configured >= 0);

    if (configured >= 0) {
        const int file_flags = ::fcntl(configured, F_GETFL);
        const int descriptor_flags = ::fcntl(configured, F_GETFD);
        CHECK(file_flags >= 0);
        CHECK(descriptor_flags >= 0);
        CHECK((file_flags & O_NONBLOCK) != 0);
        CHECK((descriptor_flags & FD_CLOEXEC) != 0);
        CHECK(::close(configured) == 0);
    }
}

void test_agent_path_safety() {
    TemporaryDirectory temporary;
    const std::string regular = temporary.file("regular.sock");
    create_regular_file(regular);
    {
        AgentServer server;
        CHECK(!server.open(regular));
    }
    struct stat status{};
    CHECK(::lstat(regular.c_str(), &status) == 0);
    CHECK(S_ISREG(status.st_mode));

    const std::string target = temporary.file("target");
    const std::string link = temporary.file("link.sock");
    create_regular_file(target);
    CHECK(::symlink(target.c_str(), link.c_str()) == 0);
    {
        AgentServer server;
        CHECK(!server.open(link));
    }
    CHECK(::lstat(link.c_str(), &status) == 0);
    CHECK(S_ISLNK(status.st_mode));
}

void test_agent_stale_socket() {
    TemporaryDirectory temporary;
    struct stat status{};
    const std::string stale = temporary.file("stale.sock");
    make_stale_socket(stale);
    {
        AgentServer server;
        REQUIRE(server.open(stale));
        CHECK(::lstat(stale.c_str(), &status) == 0);
        CHECK(S_ISSOCK(status.st_mode));
        CHECK((status.st_mode & 0777) == 0600);
    }
    CHECK(::lstat(stale.c_str(), &status) != 0 && errno == ENOENT);
}

void test_agent_live_socket() {
    TemporaryDirectory temporary;
    struct stat status{};
    const std::string live = temporary.file("live.sock");
    {
        AgentServer owner;
        AgentServer contender;
        REQUIRE(owner.open(live));
        CHECK(!contender.open(live));
        CHECK(::lstat(live.c_str(), &status) == 0);
        CHECK(S_ISSOCK(status.st_mode));
    }
}

void test_agent_accepted_socket_flags() {
    TemporaryDirectory temporary;
    const std::string accepted = temporary.file("accepted.sock");
    {
        AgentServer server;
        REQUIRE(server.open(accepted));
        const int client = connect_unix_socket(accepted);
        server.handle_listener(POLLIN);
        CHECK(server.client_capacity() > 0);

        if (server.client_capacity() > 0) {
            const int descriptor = server.client_fd(0);
            const int file_flags = ::fcntl(descriptor, F_GETFL);
            const int descriptor_flags = ::fcntl(descriptor, F_GETFD);
            CHECK(descriptor >= 0);
            CHECK(file_flags >= 0);
            CHECK(descriptor_flags >= 0);
            CHECK((file_flags & O_NONBLOCK) != 0);
            CHECK((descriptor_flags & FD_CLOEXEC) != 0);
        }

        CHECK(::close(client) == 0);
        server.handle_client(0, POLLHUP);
    }
}

void test_agent_cleanup_identity() {
    TemporaryDirectory temporary;
    struct stat status{};
    const std::string replaced = temporary.file("replaced.sock");
    {
        AgentServer server;
        REQUIRE(server.open(replaced));
        CHECK(::unlink(replaced.c_str()) == 0);
        create_regular_file(replaced);
    }
    CHECK(::lstat(replaced.c_str(), &status) == 0);
    CHECK(S_ISREG(status.st_mode));
}

void test_agent_fair_queue() {
    TemporaryDirectory temporary;
    const std::string queued = temporary.file("queued.sock");
    {
        AgentServer server;
        REQUIRE(server.open(queued));
        const int slow = connect_unix_socket(queued);
        server.handle_listener(POLLIN);
        const int ready = connect_unix_socket(queued);
        server.handle_listener(POLLIN);
        CHECK(::send(
            ready,
            "STATUS\n",
            7,
            whiteboard::platform::no_signal_send_flags()
        ) == 7);
        server.handle_client(1, POLLIN);
        std::optional<AgentRequest> request = server.take_request();
        CHECK(request.has_value());

        if (request.has_value()) {
            CHECK(request->operation == AgentOperation::Status);
            CHECK(server.reply(request->client, "OK 0 STATUS\n"));
            server.handle_client(1, POLLOUT);
        }

        char response[32]{};
        const ssize_t size = ::recv(ready, response, sizeof(response), 0);
        CHECK(size == 12);
        CHECK(std::string_view(response, static_cast<std::size_t>(size)) ==
              "OK 0 STATUS\n");
        CHECK(::close(slow) == 0);
        server.handle_client(0, POLLHUP);
        CHECK(::close(ready) == 0);
    }
}

void test_agent_response_status() {
    CHECK(agent_response_status("OK 1 STATUS\n") ==
          AgentResponseStatus::Ok);
    CHECK(agent_response_status("ERR missing\n") ==
          AgentResponseStatus::Error);
    CHECK(agent_response_status("garbage\n") ==
          AgentResponseStatus::Invalid);
}

void test_agent_snapshot_request() {
    TemporaryDirectory temporary;
    const std::string snapshot_socket = temporary.file("snapshot.sock");
    {
        AgentServer server;
        REQUIRE(server.open(snapshot_socket));
        const int client = connect_unix_socket(snapshot_socket);
        server.handle_listener(POLLIN);
        constexpr std::string_view command =
            "SNAPSHOT 42 3 5 7\n";
        CHECK(::send(
            client,
            command.data(),
            command.size(),
            whiteboard::platform::no_signal_send_flags()
        ) == static_cast<ssize_t>(command.size()));
        server.handle_client(0, POLLIN);
        std::optional<AgentRequest> request = server.take_request();
        CHECK(request.has_value());

        if (request.has_value()) {
            CHECK(request->operation == AgentOperation::Snapshot);
            CHECK(request->snapshot_revision_set);
            CHECK(request->expected_revision == 42);
            CHECK(request->snapshot_card_cursor == 3);
            CHECK(request->snapshot_edge_cursor == 5);
            CHECK(request->snapshot_glyph_cursor == 7);
        }

        CHECK(::close(client) == 0);
    }

    const std::string initial_snapshot_socket =
        temporary.file("snapshot-initial.sock");
    {
        AgentServer server;
        REQUIRE(server.open(initial_snapshot_socket));
        const int client = connect_unix_socket(initial_snapshot_socket);
        server.handle_listener(POLLIN);
        constexpr std::string_view command = "SNAPSHOT - 0 0 0\n";
        CHECK(::send(
            client,
            command.data(),
            command.size(),
            whiteboard::platform::no_signal_send_flags()
        ) == static_cast<ssize_t>(command.size()));
        server.handle_client(0, POLLIN);
        std::optional<AgentRequest> request = server.take_request();
        CHECK(request.has_value());

        if (request.has_value()) {
            CHECK(request->operation == AgentOperation::Snapshot);
            CHECK(!request->snapshot_revision_set);
        }

        CHECK(::close(client) == 0);
    }
}

AgentRequest parse_agent_request(
    TemporaryDirectory& temporary,
    std::string_view socket_name,
    std::string_view command
) {
    AgentRequest result;
    AgentServer server;
    const std::string path = temporary.file(socket_name);
    REQUIRE(server.open(path));
    const int client = connect_unix_socket(path);
    server.handle_listener(POLLIN);
    CHECK(::send(
        client,
        command.data(),
        command.size(),
        whiteboard::platform::no_signal_send_flags()
    ) == static_cast<ssize_t>(command.size()));
    server.handle_client(0, POLLIN);
    std::optional<AgentRequest> request = server.take_request();
    CHECK(request.has_value());

    if (request.has_value()) {
        result = std::move(*request);
    }

    CHECK(::close(client) == 0);
    return result;
}

void test_agent_guarded_mutations() {
    TemporaryDirectory temporary;
    const AgentRequest guarded_connect = parse_agent_request(
        temporary,
        "guarded-connect.sock",
        "CONNECT 4 5 99\n"
    );
    CHECK(guarded_connect.operation == AgentOperation::ConnectCards);
    CHECK(guarded_connect.card == 4);
    CHECK(guarded_connect.target_card == 5);
    CHECK(guarded_connect.mutation_revision_set);
    CHECK(guarded_connect.expected_revision == 99);

    constexpr std::string_view create_body = "note 0 0 12 5\n";
    std::string create_request = "CREATE_CARDS 99 ";
    create_request.append(std::to_string(create_body.size()));
    create_request.push_back('\n');
    create_request.append(create_body);
    const AgentRequest guarded_create = parse_agent_request(
        temporary,
        "guarded-create.sock",
        create_request
    );
    CHECK(guarded_create.operation == AgentOperation::CreateCards);
    CHECK(guarded_create.mutation_revision_set);
    CHECK(guarded_create.expected_revision == 99);
    CHECK(guarded_create.text == create_body);
}

void test_agent_incomplete_request() {
    TemporaryDirectory temporary;
    const std::string incomplete_socket = temporary.file("incomplete.sock");
    {
        AgentServer server;
        REQUIRE(server.open(incomplete_socket));
        const int client = connect_unix_socket(incomplete_socket);
        server.handle_listener(POLLIN);
        constexpr std::string_view command = "CREATE_CARDS 99 20\nnote";
        CHECK(::send(
            client,
            command.data(),
            command.size(),
            whiteboard::platform::no_signal_send_flags()
        ) == static_cast<ssize_t>(command.size()));
        server.handle_client(0, POLLIN);
        CHECK(!server.take_request().has_value());
        CHECK(::shutdown(client, SHUT_WR) == 0);
        server.handle_client(0, POLLIN);
        server.handle_client(0, POLLOUT);
        char response[64]{};
        const ssize_t response_size = ::recv(client, response, sizeof(response), 0);
        CHECK(response_size == 23);
        CHECK(std::string_view(response, static_cast<std::size_t>(response_size)) ==
              "ERR incomplete_request\n");
        CHECK(::close(client) == 0);
    }
}

struct SnapshotFixture {
    App app{80, 24};
    std::string expected;

    SnapshotFixture() {
    Card first = make_plain_text_note({-12, 8});
    TextCardData& text = std::get<TextCardData>(first.data);
    text.lines = {"中文", "END", "", std::string(1024, 'x')};
    const CardId first_id = app.add_card(std::move(first));
    const CardId second_id = app.add_card(
        make_markdown_card({30, -4})
    );
    REQUIRE(first_id != kNoCard);
    REQUIRE(second_id != kNoCard);

    Edge edge;
    edge.source = {first_id, PortSide::Right};
    edge.target = {second_id, PortSide::Left};
    edge.route_bounds = {-1, -2, 31, 9};
    edge.points = {{-1, 8}, {30, 8}};
    REQUIRE(app.board.add_edge(std::move(edge)) != kNoEdge);

    for (i64 index = 0; index < 40; ++index) {
        CHECK(app.glyphs.insert({index * 2, 50}, U'A'));
    }

    std::ostringstream complete;
    CHECK(whiteboard::verification::write_canonical_snapshot(
        complete,
        app.board,
        app.spatial,
        app.glyphs,
        app.formats
    ));
    expected = complete.str();
    CHECK(expected.starts_with("WHITEBOARD-SNAPSHOT 2\nMETA "));
    CHECK(expected.ends_with("END\n"));
    CHECK(expected.find("中文\nEND\n") != std::string::npos);
    }
};

void test_snapshot_pagination() {
    SnapshotFixture fixture;
    App& app = fixture.app;
    const std::string& expected = fixture.expected;
    whiteboard::verification::CanonicalSnapshotCursor cursor;
    std::string paginated = "WHITEBOARD-SNAPSHOT 2\n";
    std::size_t pages = 0;

    for (;;) {
        whiteboard::verification::CanonicalSnapshotPage page;
        const auto result =
            whiteboard::verification::make_canonical_snapshot_page(
                app.board,
                app.spatial,
                app.glyphs,
                app.formats,
                cursor,
                256,
                page
            );
        CHECK(result == whiteboard::verification::
            CanonicalSnapshotResult::Success);
        paginated.append(page.body);
        ++pages;

        if (page.done) {
            break;
        }

        CHECK(page.next != cursor);
        cursor = page.next;
    }

    paginated.append("END\n");
    CHECK(pages > 1);
    CHECK(paginated == expected);
}

void test_snapshot_boundaries() {
    SnapshotFixture fixture;
    App& app = fixture.app;
    const std::string& expected = fixture.expected;
    whiteboard::verification::CanonicalSnapshotPage invalid_page;
    CHECK(
        whiteboard::verification::make_canonical_snapshot_page(
            app.board,
            app.spatial,
            app.glyphs,
            app.formats,
            {.card = UINT64_C(3) << 32, .edge = 0, .glyph = 0},
            256,
            invalid_page
        ) == whiteboard::verification::
            CanonicalSnapshotResult::InvalidCursor
    );
    CHECK(
        whiteboard::verification::make_canonical_snapshot_page(
            app.board,
            app.spatial,
            app.glyphs,
            app.formats,
            {},
            1,
            invalid_page
        ) == whiteboard::verification::
            CanonicalSnapshotResult::RecordTooLarge
    );
    const std::size_t metadata_begin =
        std::string_view{whiteboard::verification::kCanonicalSnapshotMagic}.size();
    const std::size_t metadata_size =
        expected.find('\n', metadata_begin) + 1 - metadata_begin;
    CHECK(
        whiteboard::verification::make_canonical_snapshot_page(
            app.board,
            app.spatial,
            app.glyphs,
            app.formats,
            {},
            metadata_size,
            invalid_page
        ) == whiteboard::verification::
            CanonicalSnapshotResult::RecordTooLarge
    );
}

std::string native_bytes(const App& app) {
    std::ostringstream output(std::ios::binary);
    CHECK(write_main_file_content(output, app.board, app.glyphs));
    return output.str();
}

void test_storage_standalone_round_trip() {
    TemporaryDirectory temporary;
    App app{80, 24};
    populate_standalone_fixture(app);
    const CardId removed = 7;
    const std::string expected = native_bytes(app);
    const u64 revision = app.revision;
    const std::string original = temporary.file("original.tiwb");
    REQUIRE(whiteboard::native::save(app, original));
    CHECK(!app.dirty());
    CHECK(app.revision == revision);
    CHECK(read_file(original) == expected);
    const std::string elsewhere = temporary.file("empty");
    REQUIRE(std::filesystem::create_directory(elsewhere));
    const std::string moved = elsewhere + "/renamed.tiwb";
    std::filesystem::rename(original, moved);
    // An incomplete temporary file is neither consulted nor altered.
    const std::string sidecar = elsewhere + "/.renamed.tiwb.tmp.interrupted";
    { std::ofstream output(sidecar); output << "incomplete"; }
    App loaded{80, 24};
    REQUIRE(whiteboard::native::load(loaded, moved));
    CHECK(native_bytes(loaded) == expected);
    CHECK(loaded.board.cards.size() == app.board.cards.size());
    CHECK(!loaded.board.cards[removed].has_value());
    CHECK(loaded.board.edges.size() == 2);
    CHECK(!loaded.board.edges[1].has_value());
    CHECK(loaded.spatial.validate());
    CHECK(loaded.history.entries.empty());
    CHECK(!loaded.dirty());
    CHECK(read_file(sidecar) == "incomplete");
    REQUIRE(whiteboard::native::save(loaded, moved));
    CHECK(read_file(moved) == expected);
    CHECK(read_file(sidecar) == "incomplete");
}

void test_storage_memory_transaction() {
    App source{80, 24};
    populate_standalone_fixture(source);
    const std::string bytes = native_bytes(source);
    App target{80, 24};
    REQUIRE(target.add_card(make_plain_text_note({0, 0}, 12, 5)) == 0);
    target.begin_card(0);
    const std::string before = native_bytes(target);
    const u64 revision = target.revision;
    std::istringstream limited(bytes, std::ios::binary);
    CHECK(!target.load(limited, bytes.size(), 1));
    CHECK(native_bytes(target) == before);
    CHECK(target.revision == revision);
    CHECK(target.session.active == 0);
    CHECK(target.dirty());
    std::istringstream input(bytes, std::ios::binary);
    REQUIRE(target.load(input, bytes.size()));
    CHECK(native_bytes(target) == bytes);
    CHECK(target.session.active == kNoCard);
    CHECK(target.history.entries.empty());
    CHECK(target.spatial.validate());
    CHECK(!target.dirty());
    const u64 saved = target.revision;
    REQUIRE(target.add_card(make_plain_text_note({300, 0}, 12, 5)) != kNoCard);
    CHECK(!target.mark_saved(saved));
    CHECK(target.dirty());
    CHECK(target.mark_saved(target.revision));
    CHECK(!target.dirty());
}

void test_storage_load_failure_preserves_document() {
    TemporaryDirectory temporary;
    App app{80, 24};
    REQUIRE(app.add_card(make_plain_text_note({1, 2}, 12, 5)) == 0);
    app.begin_card(0);
    const std::string before = native_bytes(app);
    const auto revision = app.revision;
    const auto history_size = app.history.entries.size();
    const auto active = app.session.active;
    const std::string path = temporary.file("damaged.tiwb");
    for (const std::string& bytes : {before.substr(0, before.size() - 1), before + "extra"}) {
        { std::ofstream output(path, std::ios::binary); output << bytes; }
        CHECK(!whiteboard::native::load(app, path));
        CHECK(native_bytes(app) == before);
        CHECK(app.revision == revision);
        CHECK(app.history.entries.size() == history_size);
        CHECK(app.session.active == active);
        CHECK(app.dirty());
        CHECK(app.spatial.validate());
    }
    CHECK(!whiteboard::native::save(app, temporary.file("absent/board.tiwb")));
    CHECK(app.dirty());
    CHECK(app.revision == revision);
    CHECK(!app.file_error.empty());
}

void test_storage_atomic_publication_outcomes() {
    TemporaryDirectory temporary;
    const std::string target = temporary.file("board.tiwb");
    create_regular_file(target);
    for (AtomicFileFault fault : {AtomicFileFault::FileSync, AtomicFileFault::Close,
                                  AtomicFileFault::Rename, AtomicFileFault::NoSpace}) {
        AtomicFileWriter writer(target, fault);
        REQUIRE(writer.good());
        writer.stream() << "new";
        CHECK(!writer.commit());
        CHECK(!writer.published());
        CHECK(read_file(target) == "keep");
    }
    {
        AtomicFileWriter writer(target, AtomicFileFault::DirectorySync);
        writer.stream() << "published";
        CHECK(!writer.commit());
        CHECK(writer.published());
        CHECK(read_file(target) == "published");
    }
    {
        const std::string fresh = temporary.file("fresh.tiwb");
        AtomicFileWriter writer(fresh);
        writer.stream() << "created";
        CHECK(writer.commit());
        CHECK(writer.published());
        CHECK(read_file(fresh) == "created");
    }
}

void test_coordinate_geometry() {
    CHECK((rect_at({-4, 8}, {7, 3}) == Rect{-4, 8, 3, 11}));
    CHECK((selection_rect({4, 9}, {-2, 3}) == Rect{-2, 3, 5, 10}));

    Rect checked;
    CHECK(checked_rect_at(
        {std::numeric_limits<i64>::max() - 4, 0},
        {4, 1},
        checked
    ));
    CHECK(!checked_rect_at(
        {std::numeric_limits<i64>::max(), 0},
        {1, 1},
        checked
    ));
    CHECK(!checked_point_rect(
        {0, std::numeric_limits<i64>::max()},
        checked
    ));
    CHECK(!checked_selection_rect(
        {std::numeric_limits<i64>::max(), 0},
        {std::numeric_limits<i64>::max(), 0},
        checked
    ));

    Pos translated;
    CHECK(!checked_translate(
        {std::numeric_limits<i64>::min(), 0},
        {-1, 0},
        translated
    ));
    CHECK(!checked_translate(
        {std::numeric_limits<i64>::max(), 0},
        {1, 0},
        translated
    ));
}

void test_coordinate_app_mutation() {
    App app(80, 24);
    Card valid = make_plain_text_note({
        std::numeric_limits<i64>::max() - 32,
        0,
    });
    const CardId id = app.add_card(std::move(valid));
    REQUIRE(id != kNoCard);
    CHECK(!app.move_card(id, {std::numeric_limits<i64>::max(), 0}));
    CHECK(app.board.get(id).pos.x ==
          std::numeric_limits<i64>::max() - 32);

    Card invalid = make_plain_text_note({
        std::numeric_limits<i64>::max(),
        0,
    });
    const u64 revision = app.revision;
    CHECK(app.add_card(std::move(invalid)) == kNoCard);
    CHECK(app.revision == revision);
    CardData missing_replacement = TextCardData{};
    CHECK(!app.replace_card(
        kNoCard,
        std::move(missing_replacement)
    ));

    Edge invalid_edge;
    invalid_edge.source.card = id;
    invalid_edge.target.card = kNoCard;
    invalid_edge.points = {{0, 0}, {1, 0}};
    CHECK(app.add_edge(std::move(invalid_edge)) == kNoEdge);
    CHECK(app.revision == revision);

    CHECK(!app.erase_card(kNoCard));
    CHECK(app.revision == revision);
    const CardId invalid_batch[]{id, id};
    CHECK(!app.erase_cards(invalid_batch, 2));
    CHECK(app.has_card(id));
    CHECK(app.revision == revision);

    const std::vector<GlyphCell> invalid_glyph_batch{
        {{0, 0}, U'A'},
        {{1, 0}, U'\u0301'},
    };
    CHECK(!app.write_glyphs(invalid_glyph_batch));
    CHECK(app.glyphs.cells.empty());
}

void test_coordinate_screen_bounds() {
    bool negative_screen_rejected = false;

    try {
        Screen invalid_screen(-1, 1);
    } catch (const std::invalid_argument&) {
        negative_screen_rejected = true;
    }

    CHECK(negative_screen_rejected);
    Screen stable_screen(2, 2);

    try {
        stable_screen.resize(-1, 2);
    } catch (const std::invalid_argument&) {
    }

    CHECK(stable_screen.width() == 2);
    CHECK(stable_screen.height() == 2);
}

void test_coordinate_thumbnail_bounds() {
    const CardFormats formats = make_card_formats();
    PngScreenshot stale_image;
    stale_image.bytes = "stale";
    stale_image.width = 1;
    stale_image.height = 1;
    Board empty_board;
    CardSpatial empty_spatial;
    CHECK(board_thumbnail_png(
        empty_board,
        empty_spatial,
        formats,
        kBoardThumbnailMinimumSide - 1,
        BoardThumbnailLabel::Name,
        nullptr,
        stale_image
    ) == BoardThumbnailResult::Failed);
    CHECK(stale_image.bytes.empty());
    CHECK(stale_image.width == 0);
    CHECK(stale_image.height == 0);
}

void test_overview_geometry() {
    App app{80, 24};
    Rect bounds;
    CHECK(!board_overview_bounds(app.board, app.spatial, bounds, &app.glyphs));
    const CardId id = app.add_card(make_plain_text_note({-30, -20}, 12, 5));
    REQUIRE(id != kNoCard);
    const auto revision = app.revision;
    REQUIRE(board_overview_bounds(app.board, app.spatial, bounds));
    CHECK((bounds == Rect{-30, -20, -18, -15}));
    CHECK(app.revision == revision);
    PngScreenshot thumbnail;
    REQUIRE(board_thumbnail_png(app.board, app.spatial, app.formats, 96,
        BoardThumbnailLabel::CardId, &bounds, thumbnail) == BoardThumbnailResult::Success);
    CHECK(thumbnail.width == 96);
    CHECK(thumbnail.height == 59);
    CHECK(!thumbnail.bytes.empty());
    REQUIRE(app.glyphs.insert({-100, 40}, U'「'));
    REQUIRE(board_overview_bounds(app.board, app.spatial, bounds, &app.glyphs));
    CHECK((bounds == Rect{-100, -20, -18, 41}));
    REQUIRE(app.erase_card(id));
    REQUIRE(board_overview_bounds(app.board, app.spatial, bounds, &app.glyphs));
    CHECK((bounds == Rect{-100, 40, -98, 41}));
    CHECK(!board_overview_bounds(app.board, app.spatial, bounds));

    const i64 maximum = std::numeric_limits<i64>::max();
    const i64 minimum = std::numeric_limits<i64>::min();
    for (i64 origin : {minimum, i64{-100}, maximum - 100}) {
        const BoardProjection projection{{origin, origin, origin + 80, origin + 40}, 2, 16};
        CHECK(projection.x(origin + 40) == 0.5);
        CHECK(projection.y(origin + 20) == 0.5);
        CHECK((projection.world(0.5, 0.5) == Pos{origin + 40, origin + 20}));
        CHECK((projection.world(1, 1) == Pos{origin + 79, origin + 39}));
        CHECK(projection.floor(origin + 10, origin) == 36);
        CHECK(projection.ceil(origin + 10, origin) == 36);
        CHECK(projection.point(origin + 10, origin) == 36);
    }
    const BoardProjection entire{{minimum, minimum, maximum, maximum}};
    CHECK((entire.world(0, 0) == Pos{minimum, minimum}));
    CHECK((entire.world(1, 1) == Pos{maximum - 1, maximum - 1}));
    CHECK(std::abs(entire.x(0) - 0.5) < 1e-15);
    for (double invalid : {-1.0, 1.1, std::numeric_limits<double>::infinity(), std::numeric_limits<double>::quiet_NaN()}) {
        bool rejected = false;
        try { entire.world(invalid, 0.5); } catch (const std::runtime_error&) { rejected = true; }
        CHECK(rejected);
    }
    Board dormant;
    dormant.edges.emplace_back(std::in_place);
    dormant.edges[0]->points = {{-500, -500}, {500, 500}};
    CHECK(!board_overview_bounds(dormant, CardSpatial{}, bounds));
}

void test_csv_round_trip() {
    CsvCardData original;
    original.cells = {
        {""}, {"name", "value"}, {"alpha", "x,y"},
        {"q", "a\"b"}, {"line\r\nbreak"}, {"", ""}, {""},
    };
    std::stringstream stream;
    write_csv(stream, original);
    CsvCardData decoded;
    CHECK(read_csv(stream, decoded));
    CHECK(decoded.cells == original.cells);
    CHECK(stream.str().starts_with("\"\"\n"));
    CHECK(stream.str().ends_with("\n\"\""));
}

void test_csv_quoted_rows() {
    std::istringstream input{"\"line 1\nline 2\",\"a\"\"b\"\r\n,"};
    CsvCardData value;
    CHECK(read_csv(input, value));
    CHECK(value.cells == std::vector<std::vector<std::string>>({
        {"line 1\nline 2", "a\"b"},
        {"", ""},
    }));
}

void test_csv_rejections() {
    const auto rejects = [](std::string_view content, CsvErrorCode code) {
        std::istringstream input{std::string{content}};
        CsvCardData value;
        value.cells = {{"preserved"}};
        CsvParseError error;
        CHECK(!read_csv(input, value, &error));
        CHECK(error.code == code);
        CHECK(value.cells ==
              std::vector<std::vector<std::string>>({{"preserved"}}));
    };

    rejects("\"unterminated", CsvErrorCode::UnterminatedQuote);
    rejects("a\"b", CsvErrorCode::UnexpectedQuote);
    rejects("\"a\"x", CsvErrorCode::UnexpectedAfterQuote);
}

void test_unicode_width_contract() {
    CHECK(decode_utf8("A", 0).codepoint == U'A');
    CHECK(decode_utf8("\xE4\xB8\xAD", 0).codepoint == U'中');
    CHECK(display_rune(U'A').width == 1);
    CHECK(display_rune(U'中').width == 2);
    CHECK(display_rune(U'\u0301').width == 0);
    CHECK(unicode_mark(U'\u0301'));
    CHECK(unicode_mark(U'\u0903'));
    CHECK(display_rune(U'\u0903').width == 1);
    CHECK(!stored_glyph(U'\u0301'));
    CHECK(!stored_glyph(U'\u0903'));
}

void test_unicode_clusters() {
    const std::string cluster = "e\xCC\x81X";
    CHECK(next_text_cluster_byte(cluster, 0) == 3);
    CHECK(previous_text_cluster_byte(cluster, 3) == 0);
    CHECK(next_text_cluster_byte(cluster, 3) == 4);
    CHECK(valid_utf8_display_text(cluster));
    CHECK(!valid_utf8_display_text("\xCC\x81"));
    CHECK(!valid_utf8_display_text(std::string_view{"\xC0\xAF", 2}));
}

void test_unicode_screen_combining() {
    Screen screen(4, 1);
    screen.paint(0, 0, display_rune(U'e'), {}, 1, 0, 0);
    screen.paint(1, 0, display_rune(U'\u0301'), {}, 1, 0, 1);
    CHECK(screen.at(0, 0).combining == std::u32string{U'\u0301'});
    CHECK(screen.at(1, 0).glyph == U' ');
}

void test_terminal_presentation_diff() {
    TerminalPresenter presenter;
    Screen screen(4, 2);

    const std::string first{presenter.compose(screen, "ready")};
    CHECK(first.find("\x1b[1;1H") != std::string::npos);
    CHECK(first.find("\x1b[2;1H") != std::string::npos);
    CHECK(first.find("\x1b[3;1H\x1b[0;7mread") !=
          std::string::npos);
    CHECK(presenter.compose(screen, "ready").empty());

    screen.paint(1, 0, display_rune(U'X'), {}, 7);
    CHECK(
        presenter.compose(screen, "ready") ==
        "\x1b[1;2H\x1b[0;37;40mX\x1b[0m"
    );
    CHECK(presenter.compose(screen, "ready").empty());

    screen.paint(1, 0, display_rune(U'X'), {}, 9, 4, 2);
    CHECK(presenter.compose(screen, "ready").empty());

    CHECK(
        presenter.compose(screen, "next") ==
        "\x1b[3;1H\x1b[0;7mn\x1b[3;3Hxt\x1b[0m"
    );
    CHECK(
        presenter.compose(screen, "nest") ==
        "\x1b[3;3H\x1b[0;7ms\x1b[0m"
    );

    Screen resized(5, 1);
    const std::string resized_frame{
        presenter.compose(resized, "nest")
    };
    CHECK(resized_frame.find("\x1b[1;1H") != std::string::npos);
    CHECK(resized_frame.find("\x1b[2;1H\x1b[0;7mnest ") !=
          std::string::npos);
}

void test_terminal_presentation_wide_cell() {
    TerminalPresenter presenter;
    Screen screen(4, 1);
    presenter.compose(screen, "");

    screen.paint(1, 0, display_rune(U'中'), {}, 3);
    screen.paint(3, 0, display_rune(U'\u0301'), {}, 3);
    CHECK(
        presenter.compose(screen, "") ==
        "\x1b[1;2H\x1b[0;37;40m"
        "\xE4\xB8\xAD\xCC\x81\x1b[0m"
    );

    screen.clear();
    CHECK(
        presenter.compose(screen, "") ==
        "\x1b[1;2H\x1b[0;37;40m  \x1b[0m"
    );
}

void dump_unicode_contract() {
    constexpr char32_t samples[] = {
        U'A',
        U'\u0301',
        U'\u0903',
        U'\u00AD',
        U'\u2028',
        U'中',
        U'\U0001F600',
        static_cast<char32_t>(0x0378),
    };

    for (char32_t codepoint : samples) {
        std::cout
            << static_cast<u32>(codepoint) << ','
            << rune_cell_width(codepoint) << ','
            << static_cast<int>(unicode_mark(codepoint)) << ','
            << static_cast<int>(unicode_whitespace(codepoint)) << '\n';
    }
}

void test_spatial_floor_division() {
    CHECK(card_spatial_floor_div(0, 64) == 0);
    CHECK(card_spatial_floor_div(63, 64) == 0);
    CHECK(card_spatial_floor_div(64, 64) == 1);
    CHECK(card_spatial_floor_div(-1, 64) == -1);
    CHECK(card_spatial_floor_div(-64, 64) == -1);
    CHECK(card_spatial_floor_div(-65, 64) == -2);
}

void populate_spatial(CardSpatial& spatial) {
    spatial.change(0, {-65, -33, -63, -31});
    spatial.change(1, {-64, -32, 0, 0});
    spatial.change(2, {-1, -1, 65, 33});
    spatial.change(3, {64, 32, 66, 34});
    spatial.change(4, {1, 1, 2, 2});
}

void test_spatial_queries() {
    CardSpatial spatial;
    populate_spatial(spatial);
    CHECK(spatial.validate());
    CHECK(spatial.live_count() == 5);
    CHECK(spatial.occupied_cell_count() != 0);
    CHECK(spatial.bucket_entry_count() > spatial.live_count());

    std::vector<CardId> found;
    CHECK(spatial.query({-64, -32, 0, 0}, [&](CardId id) {
        found.push_back(id);
        return true;
    }));
    std::sort(found.begin(), found.end());
    CHECK(found == std::vector<CardId>({0, 1, 2}));

    found.clear();
    CHECK(spatial.query({0, 0, 64, 32}, [&](CardId id) {
        found.push_back(id);
        return true;
    }));
    std::sort(found.begin(), found.end());
    CHECK(found == std::vector<CardId>({2, 4}));

    u32 visits = 0;
    CHECK(!spatial.query({-100, -100, 100, 100}, [&](CardId) {
        ++visits;
        return false;
    }));
    CHECK(visits == 1);
}

void test_spatial_updates() {
    CardSpatial spatial;
    populate_spatial(spatial);
    spatial.change(4, {2, 2, 3, 3});
    CHECK(spatial.validate());
    spatial.change(4, {128, 64, 130, 66});
    CHECK(spatial.validate());

    std::vector<CardId> found;
    CHECK(spatial.query({0, 0, 64, 32}, [&](CardId id) {
        found.push_back(id);
        return true;
    }));
    CHECK(found == std::vector<CardId>({2}));
}

void test_spatial_nested_query() {
    CardSpatial spatial;
    populate_spatial(spatial);
    std::array<u8, 5> outer_seen{};
    u32 outer_visits = 0;
    bool nested = false;
    CHECK(spatial.query({-100, -100, 200, 100}, [&](CardId id) {
        CHECK(id < outer_seen.size());
        CHECK(outer_seen[id] == 0);
        outer_seen[id] = 1;
        ++outer_visits;

        if (!nested) {
            nested = true;
            CHECK(spatial.query({0, 0, 64, 32}, [](CardId) {
                return true;
            }));
        }
        return true;
    }));
    CHECK(outer_visits == spatial.live_count());
}

void test_spatial_erase_and_extreme_query() {
    CardSpatial spatial;
    populate_spatial(spatial);
    spatial.erase(1);
    CHECK(spatial.validate());
    CHECK(spatial.live_count() == 4);

    u32 visits = 0;
    CHECK(spatial.query(
        {
            std::numeric_limits<i64>::min(),
            std::numeric_limits<i64>::min(),
            std::numeric_limits<i64>::max(),
            std::numeric_limits<i64>::max(),
        },
        [&](CardId) {
            ++visits;
            return true;
        }
    ));
    CHECK(visits == spatial.live_count());
}

void test_text_styles() {
    TextCardData styled;
    styled.lines = {"0123456789"};
    const Style outer{1, 0, AttrNone};
    const Style inner{2, 0, AttrBold};
    styled.styles.emplace_back(
        0,
        TextSpan{0, 0, 10, outer}
    );
    styled.styles.emplace_back(
        0,
        TextSpan{0, 2, 5, inner}
    );
    canonicalize_text_styles(styled);
    CHECK(styled.styles.size() == 1);
    CHECK(styled.styles[0].spans.size() == 3);
    CHECK(styled.styles[0].spans[0].begin_byte == 0);
    CHECK(styled.styles[0].spans[0].end_byte == 2);
    CHECK(styled.styles[0].spans[0].style == outer);
    CHECK(styled.styles[0].spans[1].begin_byte == 2);
    CHECK(styled.styles[0].spans[1].end_byte == 5);
    CHECK(styled.styles[0].spans[1].style == inner);
    CHECK(styled.styles[0].spans[2].begin_byte == 5);
    CHECK(styled.styles[0].spans[2].end_byte == 10);
    CHECK(styled.styles[0].spans[2].style == outer);

    TextEdit style_edit;
    style_edit.old_range = {{0, 2}, {0, 5}};
    style_edit.new_end = {0, 4};
    edit_text_styles(styled.styles, style_edit);
    CHECK(styled.styles.size() == 1);
    CHECK(styled.styles[0].spans.size() == 2);
    CHECK(styled.styles[0].spans[0].end_byte == 2);
    CHECK(styled.styles[0].spans[1].begin_byte == 4);
    CHECK(styled.styles[0].spans[1].end_byte == 9);
}

void test_text_performance_100k() {
    const Style outer{1, 0, AttrNone};
    TextLines lines;
    TextStyles styles;
    lines.reserve(100'000);
    styles.reserve(100'000);

    for (u32 row = 0; row < 100'000; ++row) {
        lines.emplace_back("abcd");
        styles.emplace_back(
            row,
            TextSpan{row, 0, 4, outer}
        );
    }

    canonicalize_text_styles(styles, lines);
    CHECK(styles.size() == 100'000);
    CHECK(text_style_span_count(styles) == 100'000);

    TextByteIndex index;
    index.rebuild(lines);
    CHECK(index.row_start(lines, 99'999) == 99'999U * 5U);

    PreparedTextEdit middle = prepare_text_edit(
        lines,
        {{50'000, 4}, {50'000, 4}},
        "x",
        &index
    );
    const TextEdit middle_edit = middle.edit;
    CHECK(middle_edit.start_byte == 50'000U * 5U + 4U);
    apply_text_edit(lines, std::move(middle));
    index.after_edit(lines, middle_edit);
    CHECK(index.row_start(lines, 99'999) == 99'999U * 5U + 1U);

    PreparedTextEdit top = prepare_text_edit(
        lines,
        {{0, 0}, {0, 0}},
        "a\nb",
        &index
    );
    const TextEdit top_edit = top.edit;
    apply_text_edit(lines, std::move(top));
    index.after_edit(lines, top_edit);
    CHECK(lines.size() == 100'001);
    CHECK(index.row_start(lines, 100'000) == 99'999U * 5U + 4U);
}

} // namespace

int main(int argc, char** argv) {
    std::setlocale(LC_CTYPE, "");

    if (argc == 2 && std::string_view{argv[1]} == "unicode-dump") {
        dump_unicode_contract();
        return 0;
    }

    if (argc != 3 || std::string_view{argv[1]} != "--case") {
        std::cerr << "usage: whiteboard_tests --case NAME\n";
        return 2;
    }

    struct TestCase {
        std::string_view name;
        void (*run)();
    };
    constexpr TestCase cases[] = {
#define WHITEBOARD_TEST_CASE(name, function) {name, function},
#include "whiteboard_test_cases.def"
#undef WHITEBOARD_TEST_CASE
    };

    const std::string_view selected = argv[2];
    const auto found = std::find_if(
        std::begin(cases),
        std::end(cases),
        [selected](const TestCase& test_case) {
            return test_case.name == selected;
        }
    );

    if (found == std::end(cases)) {
        std::cerr << "unknown test case: " << selected << '\n';
        return 2;
    }

    try {
        found->run();
    } catch (const RequirementFailure&) {
    }

    return failures == 0 ? 0 : 1;
}
