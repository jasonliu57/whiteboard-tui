#pragma once

#include "../text/utf8.hpp"
#include "../types.hpp"

#include <charconv>
#include <string>
#include <string_view>

static void normalize_newlines(
    std::string_view text,
    std::string& result
) {
    result.clear();
    result.reserve(text.size());

    for (std::size_t i = 0; i < text.size(); ++i) {
        if (text[i] == '\r') {
            result.push_back('\n');

            if (i + 1 < text.size() && text[i + 1] == '\n') {
                ++i;
            }
        } else {
            result.push_back(text[i]);
        }
    }

}

class InputDecoder {
public:
    std::size_t pending_size() const noexcept { return buffer_.size() - head_; }

    void append(std::string_view bytes) {
        buffer_.append(bytes);
    }

    bool next(InputEvent& event, bool flush_escape = false) {
        event.key = Key::Unknown;
        event.text.clear();
        event.shift = false;
        event.ctrl = false;
        event.mouse = MouseAction::None;
        event.mouse_x = 0;
        event.mouse_y = 0;

        const std::string_view bytes = buffered_bytes();

        if (bytes.empty()) {
            return false;
        }

        if (static_cast<u8>(bytes[0]) == 0x1B) {
            return decode_escape(event, flush_escape);
        }

        const u8 first = static_cast<u8>(bytes[0]);

        switch (first) {
            case 0x01: return consume_control(event, Key::CtrlA);
            case 0x02: return consume_control(event, Key::CtrlB);
            case 0x03: return consume_control(event, Key::CtrlC);
            case 0x04: return consume_control(event, Key::CtrlD);
            case 0x05: return consume_control(event, Key::CtrlE);
            case 0x07: return consume_control(event, Key::CtrlG);
            case 0x08: return consume_control(event, Key::Backspace);
            case 0x09: return consume_control(event, Key::Tab);
            case 0x0A:
            case 0x0D: return consume_control(event, Key::Enter);
            case 0x11: return consume_control(event, Key::CtrlQ);
            case 0x12: return consume_control(event, Key::CtrlR);
            case 0x13: return consume_control(event, Key::CtrlS);
            case 0x16: return consume_control(event, Key::CtrlV);
            case 0x18: return consume_control(event, Key::CtrlX);
            case 0x19: return consume_control(event, Key::CtrlY);
            case 0x1A: return consume_control(event, Key::CtrlZ);
            case 0x7F: return consume_control(event, Key::Backspace);
            default: break;
        }

        if (first < 0x20) {
            consume(1);
            event.key = Key::Unknown;
            return true;
        }

        std::size_t size = 0;

        while (size < bytes.size()) {
            const u8 byte = static_cast<u8>(bytes[size]);

            if (byte < 0x20 || byte == 0x7F) {
                break;
            }

            const std::size_t rune_size = utf8_size(byte);

            if (rune_size == 0) {
                if (size == 0) {
                    consume(1);
                    return true;
                }
                break;
            }

            if (size + rune_size > bytes.size()) {
                break;
            }

            const Rune rune = decode_utf8(bytes, static_cast<u32>(size));

            if (!rune.valid || rune_cell_width(rune.codepoint) < 0) {
                if (size == 0) {
                    consume(1);
                    return true;
                }
                break;
            }

            size += rune_size;
        }

        if (size == 0) {
            return false;
        }

        event.key = Key::Text;
        event.text.assign(bytes.data(), size);
        consume(size);
        return true;
    }

private:
    struct Sequence {
        std::string_view text;
        Key key;
        bool shift;
        bool ctrl;
    };

    std::string buffer_;
    std::size_t head_ = 0;

    static constexpr std::size_t kCompactThreshold = 4096;

    std::string_view buffered_bytes() const noexcept {
        return std::string_view{buffer_}.substr(head_);
    }

    void consume(std::size_t count) {
        head_ += count;

        if (head_ == buffer_.size()) {
            buffer_.clear();
            head_ = 0;
            return;
        }

        if (
            head_ >= kCompactThreshold &&
            head_ >= buffer_.size() - head_
        ) {
            buffer_.erase(0, head_);
            head_ = 0;
        }
    }

    static std::size_t utf8_size(u8 first) {
        if (first < 0x80) {
            return 1;
        }

        if (first >= 0xC2 && first <= 0xDF) {
            return 2;
        }

        if (first >= 0xE0 && first <= 0xEF) {
            return 3;
        }

        if (first >= 0xF0 && first <= 0xF4) {
            return 4;
        }

        return 0;
    }

    bool consume_control(InputEvent& event, Key key) {
        consume(1);
        event.key = key;
        return true;
    }

    static bool parse_decimal(
        std::string_view text,
        u32& value
    ) {
        const auto result = std::from_chars(
            text.data(),
            text.data() + text.size(),
            value
        );
        return
            !text.empty() &&
            result.ec == std::errc{} &&
            result.ptr == text.data() + text.size();
    }

    bool decode_mouse(InputEvent& event, bool flush_escape) {
        const std::string_view bytes = buffered_bytes();
        std::size_t end = 3;

        while (
            end < bytes.size() &&
            bytes[end] != 'M' &&
            bytes[end] != 'm'
        ) {
            ++end;
        }

        if (end == bytes.size()) {
            if (!flush_escape) {
                return false;
            }

            consume(bytes.size());
            return true;
        }

        const std::string_view packet{
            bytes.data() + 3,
            end - 3
        };
        const std::size_t first = packet.find(';');
        const std::size_t second = first == std::string_view::npos
            ? first
            : packet.find(';', first + 1);
        u32 button = 0;
        u32 mouse_x = 0;
        u32 mouse_y = 0;
        const bool valid =
            first != std::string_view::npos &&
            second != std::string_view::npos &&
            parse_decimal(packet.substr(0, first), button) &&
            parse_decimal(
                packet.substr(first + 1, second - first - 1),
                mouse_x
            ) &&
            parse_decimal(packet.substr(second + 1), mouse_y) &&
            mouse_x != 0 &&
            mouse_y != 0;
        const char terminator = bytes[end];

        consume(end + 1);

        if (!valid) {
            return true;
        }

        event.mouse_x = static_cast<i32>(mouse_x - 1);
        event.mouse_y = static_cast<i32>(mouse_y - 1);

        if ((button & 64U) != 0) {
            switch (button & 3U) {
                case 0:
                    event.key = (button & 4U) != 0
                        ? Key::Left
                        : Key::Up;
                    break;
                case 1:
                    event.key = (button & 4U) != 0
                        ? Key::Right
                        : Key::Down;
                    break;
                case 2:
                    event.key = Key::Left;
                    break;
                case 3:
                    event.key = Key::Right;
                    break;
            }

            return true;
        }

        if (terminator == 'm') {
            event.mouse = MouseAction::Release;
            return true;
        }

        if ((button & 32U) != 0) {
            switch (button & 3U) {
                case 0:
                    event.mouse = MouseAction::LeftDrag;
                    break;
                case 1:
                    event.mouse = MouseAction::MiddleDrag;
                    break;
            }

            return true;
        }

        switch (button & 3U) {
            case 0:
                event.mouse = MouseAction::LeftPress;
                break;
            case 1:
                event.mouse = MouseAction::MiddlePress;
                break;
            case 2:
                event.mouse = MouseAction::RightPress;
                break;
        }

        return true;
    }

    bool decode_escape(InputEvent& event, bool flush_escape) {
        constexpr std::string_view paste_begin = "\x1b[200~";
        constexpr std::string_view paste_end = "\x1b[201~";
        const std::string_view bytes = buffered_bytes();

        if (bytes.starts_with("\x1b[<")) {
            return decode_mouse(event, flush_escape);
        }

        if (bytes.starts_with(paste_begin)) {
            const std::size_t end = bytes.find(
                paste_end,
                paste_begin.size()
            );

            if (end == std::string_view::npos) {
                return false;
            }

            event.key = Key::Paste;
            normalize_newlines(
                bytes.substr(
                    paste_begin.size(),
                    end - paste_begin.size()
                ),
                event.text
            );

            consume(end + paste_end.size());
            return true;
        }

        static constexpr Sequence sequences[] = {
            {"\x1b[1;5A", Key::Up, false, true},
            {"\x1b[1;5B", Key::Down, false, true},
            {"\x1b[1;5C", Key::Right, false, true},
            {"\x1b[1;5D", Key::Left, false, true},
            {"\x1b[1;2A", Key::Up, true, false},
            {"\x1b[1;2B", Key::Down, true, false},
            {"\x1b[1;2C", Key::Right, true, false},
            {"\x1b[1;2D", Key::Left, true, false},
            {"\x1b[Z", Key::Tab, true, false},
            {"\x1b[A", Key::Up, false, false},
            {"\x1b[B", Key::Down, false, false},
            {"\x1b[C", Key::Right, false, false},
            {"\x1b[D", Key::Left, false, false},
            {"\x1b[H", Key::Home, false, false},
            {"\x1b[F", Key::End, false, false},
            {"\x1b[1~", Key::Home, false, false},
            {"\x1b[3~", Key::Delete, false, false},
            {"\x1b[4~", Key::End, false, false},
            {"\x1b[5~", Key::PageUp, false, false},
            {"\x1b[6~", Key::PageDown, false, false},
            {"\x1b[7~", Key::Home, false, false},
            {"\x1b[8~", Key::End, false, false},
        };

        bool partial = false;

        for (const Sequence& sequence : sequences) {
            if (bytes.starts_with(sequence.text)) {
                consume(sequence.text.size());
                event.key = sequence.key;
                event.shift = sequence.shift;
                event.ctrl = sequence.ctrl;
                return true;
            }

            if (
                bytes.size() < sequence.text.size() &&
                sequence.text.starts_with(bytes)
            ) {
                partial = true;
            }
        }

        if (
            bytes.size() < paste_begin.size() &&
            paste_begin.starts_with(bytes)
        ) {
            partial = true;
        }

        if (partial && !flush_escape) {
            return false;
        }

        if (bytes.starts_with("\x1b[")) {
            for (std::size_t i = 2; i < bytes.size(); ++i) {
                const u8 byte = static_cast<u8>(bytes[i]);

                if (byte >= 0x40 && byte <= 0x7E) {
                    consume(i + 1);
                    event.key = Key::Unknown;
                    return true;
                }
            }

            if (!flush_escape) {
                return false;
            }

            consume(bytes.size());
            event.key = Key::Unknown;
            return true;
        }

        consume(1);
        event.key = Key::Escape;
        return true;
    }
};
