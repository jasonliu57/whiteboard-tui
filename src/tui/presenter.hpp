#pragma once

#include "../decimal.hpp"
#include "../render/screen.hpp"
#include "../text/utf8.hpp"
#include "../types.hpp"

#include <algorithm>
#include <cerrno>
#include <cstddef>
#include <span>
#include <string>
#include <string_view>
#include <vector>

class TerminalPresenter {
public:
    std::string_view compose(
        const Screen& screen,
        std::string_view status
    ) {
        output_.clear();
        build_status(status, screen.width());

        const bool full =
            screen.width() != width_ ||
            screen.height() != height_;

        if (full) {
            width_ = screen.width();
            height_ = screen.height();
            previous_.resize(
                static_cast<std::size_t>(width_) * height_
            );
            previous_status_.resize(
                static_cast<std::size_t>(width_)
            );
            output_.reserve(
                static_cast<std::size_t>(width_) * height_ * 2
            );
        }

        Style current{};
        bool has_style = false;

        for (i32 y = 0; y < height_; ++y) {
            i32 x = 0;

            while (x < width_) {
                while (
                    x < width_ &&
                    !full &&
                    same_as_previous(screen, x, y)
                ) {
                    ++x;
                }

                if (x == width_) {
                    break;
                }

                const i32 begin = x;

                while (
                    x < width_ &&
                    (full || !same_as_previous(screen, x, y))
                ) {
                    ++x;
                }

                append_cursor(output_, y, begin);
                append_cells(
                    output_,
                    screen,
                    y,
                    begin,
                    x,
                    current,
                    has_style
                );
                remember(screen, y, begin, x);
            }
        }

        bool has_status_style = false;

        for (i32 x = 0; x < width_;) {
            while (
                x < width_ &&
                !full &&
                status_[x] == previous_status_[x]
            ) {
                ++x;
            }

            if (x == width_) {
                break;
            }

            const i32 begin = x;

            while (
                x < width_ &&
                (full || status_[x] != previous_status_[x])
            ) {
                ++x;
            }

            append_cursor(output_, height_, begin);

            if (!has_status_style) {
                output_.append("\x1b[0;7m");
                has_status_style = true;
            }

            append_presented_cells(output_, status_, begin, x);
            std::copy(
                status_.begin() + begin,
                status_.begin() + x,
                previous_status_.begin() + begin
            );
        }

        if (!output_.empty()) {
            output_.append("\x1b[0m");
        }

        return output_;
    }

    void reset() {
        width_ = -1;
        height_ = -1;
        previous_.clear();
        previous_status_.clear();
        status_.clear();
        output_.clear();
    }

private:
    struct PresentedCell {
        std::u32string combining;
        char32_t glyph = U' ';
        Style style{};
        u8 width = 1;

        friend bool operator==(
            const PresentedCell&,
            const PresentedCell&
        ) = default;
    };

    i32 width_ = -1;
    i32 height_ = -1;
    std::vector<PresentedCell> previous_;
    std::vector<PresentedCell> previous_status_;
    std::vector<PresentedCell> status_;
    std::string output_;

    std::size_t index(i32 x, i32 y) const {
        return static_cast<std::size_t>(y) * width_ + x;
    }

    bool same_as_previous(
        const Screen& screen,
        i32 x,
        i32 y
    ) const {
        const ScreenCell& cell = screen.at(x, y);
        const PresentedCell& previous = previous_[index(x, y)];

        if (cell.width != previous.width) {
            return false;
        }

        if (cell.width == 0) {
            return true;
        }

        return
            cell.glyph == previous.glyph &&
            cell.combining == previous.combining &&
            cell.style == previous.style;
    }

    void remember(
        const Screen& screen,
        i32 y,
        i32 begin,
        i32 end
    ) {
        for (i32 x = begin; x < end; ++x) {
            const ScreenCell& cell = screen.at(x, y);
            PresentedCell& previous = previous_[index(x, y)];
            previous.glyph = cell.glyph;
            previous.combining = cell.combining;
            previous.style = cell.style;
            previous.width = cell.width;
        }
    }

    static void append_cursor(
        std::string& output,
        i32 row,
        i32 column
    ) {
        output.append("\x1b[");
        append_decimal(output, row + 1);
        output.push_back(';');
        append_decimal(output, column + 1);
        output.push_back('H');
    }

    static void append_cells(
        std::string& output,
        const Screen& screen,
        i32 y,
        i32 begin,
        i32 end,
        Style& current,
        bool& has_style
    ) {
        for (i32 x = begin; x < end; ++x) {
            const ScreenCell& cell = screen.at(x, y);

            if (cell.width == 0) {
                continue;
            }

            if (!has_style || cell.style != current) {
                append_style(output, cell.style);
                current = cell.style;
                has_style = true;
            }

            append_utf8(output, cell.glyph);

            for (char32_t mark : cell.combining) {
                append_utf8(output, mark);
            }
        }
    }

    static void append_style(std::string& output, Style style) {
        output.append("\x1b[0");

        if ((style.attributes & AttrBold) != 0) {
            output.append(";1");
        }

        if ((style.attributes & AttrUnderline) != 0) {
            output.append(";4");
        }

        output.push_back(';');
        append_decimal(
            output,
            style.foreground < 8
                ? 30 + style.foreground
                : 90 + style.foreground - 8
        );

        output.push_back(';');
        append_decimal(
            output,
            style.background < 8
                ? 40 + style.background
                : 100 + style.background - 8
        );

        output.push_back('m');
    }

    static void append_presented_cells(
        std::string& output,
        const std::vector<PresentedCell>& cells,
        i32 begin,
        i32 end
    ) {
        for (i32 x = begin; x < end; ++x) {
            const PresentedCell& cell = cells[x];

            if (cell.width == 0) {
                continue;
            }

            append_utf8(output, cell.glyph);

            for (char32_t mark : cell.combining) {
                append_utf8(output, mark);
            }
        }
    }

    void build_status(std::string_view status, i32 width) {
        status_.assign(static_cast<std::size_t>(width), {});
        i32 x = 0;

        for (u32 byte = 0;
             byte < status.size() && x < width;) {
            const Rune rune = decode_utf8(status, byte);
            const DisplayRune display = display_rune(rune.codepoint);
            byte += rune.bytes;

            if (display.width == 0) {
                i32 lead = x - 1;

                if (lead >= 0 && status_[lead].width == 0) {
                    --lead;
                }

                if (lead >= 0) {
                    status_[lead].combining.push_back(display.glyph);
                }

                continue;
            }

            if (x + display.width > width) {
                break;
            }

            PresentedCell& lead = status_[x];
            lead.glyph = display.glyph;
            lead.width = static_cast<u8>(display.width);

            if (display.width == 2) {
                PresentedCell& continuation = status_[x + 1];
                continuation.glyph = U'\0';
                continuation.width = 0;
            }

            x += display.width;
        }
    }
};
