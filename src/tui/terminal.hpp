#pragma once

#include "presenter.hpp"
#include <sys/ioctl.h>
#include <termios.h>
#include <unistd.h>

enum class ReadResult : u8 {
    Data,
    Timeout,
    Closed,
};

class Terminal {
public:
    Terminal() = default;

    Terminal(const Terminal&) = delete;
    Terminal& operator=(const Terminal&) = delete;

    ~Terminal() {
        leave();
    }

    bool enter() {
        if (
            !::isatty(STDIN_FILENO) ||
            !::isatty(STDOUT_FILENO) ||
            ::tcgetattr(STDIN_FILENO, &original_) != 0
        ) {
            return false;
        }

        termios raw = original_;
        ::cfmakeraw(&raw);
        raw.c_iflag &= static_cast<tcflag_t>(~IXON);
        raw.c_cc[VMIN] = 0;
        raw.c_cc[VTIME] = 0;

        if (::tcsetattr(STDIN_FILENO, TCSAFLUSH, &raw) != 0) {
            return false;
        }

        active_ = true;
        refresh_size();
        presenter_.reset();

        return write_all(
            "\x1b[?1049h"
            "\x1b[?25l"
            "\x1b[?2004h"
            "\x1b[?1002h"
            "\x1b[?1006h"
            "\x1b[2J"
            "\x1b[H"
        );
    }

    void leave() {
        if (!active_) {
            return;
        }

        write_all(
            "\x1b[0m"
            "\x1b[?1002l"
            "\x1b[?1006l"
            "\x1b[?2004l"
            "\x1b[?25h"
            "\x1b[?1049l"
        );

        ::tcsetattr(STDIN_FILENO, TCSAFLUSH, &original_);
        active_ = false;
    }

    i32 width() const noexcept {
        return width_;
    }

    i32 height() const noexcept {
        return height_;
    }

    bool refresh_size() {
        winsize size{};

        if (::ioctl(STDOUT_FILENO, TIOCGWINSZ, &size) != 0) {
            return false;
        }

        const i32 width = std::max<i32>(1, size.ws_col);
        const i32 height = std::max<i32>(2, size.ws_row);
        const bool changed = width != width_ || height != height_;

        width_ = width;
        height_ = height;
        return changed;
    }

    ReadResult read_input(
        std::span<char> buffer,
        std::size_t& size
    ) {
        size = 0;
        const ssize_t count = ::read(
            STDIN_FILENO,
            buffer.data(),
            buffer.size()
        );

        if (count <= 0) {
            return count < 0 &&
                    (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK)
                ? ReadResult::Timeout
                : ReadResult::Closed;
        }

        size = static_cast<std::size_t>(count);
        return ReadResult::Data;
    }

    bool repaint(const Screen& screen, std::string_view status) {
        return write_all(presenter_.compose(screen, status));
    }

private:
    termios original_{};
    bool active_ = false;
    i32 width_ = 80;
    i32 height_ = 24;
    TerminalPresenter presenter_;

    static bool write_all(std::string_view bytes) {
        while (!bytes.empty()) {
            const ssize_t count = ::write(
                STDOUT_FILENO,
                bytes.data(),
                bytes.size()
            );

            if (count < 0) {
                if (errno == EINTR) {
                    continue;
                }

                return false;
            }

            bytes.remove_prefix(static_cast<std::size_t>(count));
        }

        return true;
    }
};
