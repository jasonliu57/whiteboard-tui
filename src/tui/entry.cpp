#include "entry.hpp"
#include "all.hpp"
#include "native_runtime.hpp"
#include "native_commands.hpp"
#include "agent.hpp"

#include <cerrno>
#include <clocale>
#include <cstddef>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <string>
#include <unistd.h>

namespace {

void write_error(const char* bytes, std::size_t size) noexcept {
    std::size_t offset = 0;

    while (offset < size) {
        const ssize_t written = ::write(
            STDERR_FILENO,
            bytes + offset,
            size - offset
        );

        if (written > 0) {
            offset += static_cast<std::size_t>(written);
        } else if (written < 0 && errno == EINTR) {
            continue;
        } else {
            return;
        }
    }
}

} // namespace

int run_whiteboard_tui(int argc, char** argv) {
    ::setlocale(LC_CTYPE, "");

    const std::string main_file =
        argc > 1 ? argv[1] : "whiteboard.tiwb";

    Terminal terminal;

    if (!terminal.enter()) {
        const char message[] =
            "whiteboard_tui: terminal init failed\n";
        write_error(message, sizeof(message) - 1);
        return EXIT_FAILURE;
    }

    try {
        NativeTui tui(terminal.width(), terminal.height(), main_file);
        return tui.run(terminal);
    } catch (const std::exception& error) {
        terminal.leave();
        constexpr char prefix[] = "whiteboard_tui: ";
        write_error(prefix, sizeof(prefix) - 1);
        write_error(error.what(), std::strlen(error.what()));
        write_error("\n", 1);
        return EXIT_FAILURE;
    }
}
