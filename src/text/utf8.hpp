#pragma once

#include "unicode_width_table.hpp"
#include "../types.hpp"

#include <string>
#include <string_view>

struct Rune {
    char32_t codepoint = U'\uFFFD';
    u32 bytes = 1;
    bool valid = true;
};

inline void append_utf8(std::string& output, char32_t codepoint) {
    if (
        codepoint > U'\U0010FFFF' ||
        (codepoint >= 0xD800 && codepoint <= 0xDFFF)
    ) {
        codepoint = U'\uFFFD';
    }

    if (codepoint <= 0x7F) {
        output.push_back(static_cast<char>(codepoint));
    } else if (codepoint <= 0x7FF) {
        output.push_back(static_cast<char>(0xC0 | (codepoint >> 6)));
        output.push_back(static_cast<char>(0x80 | (codepoint & 0x3F)));
    } else if (codepoint <= 0xFFFF) {
        output.push_back(static_cast<char>(0xE0 | (codepoint >> 12)));
        output.push_back(static_cast<char>(
            0x80 | ((codepoint >> 6) & 0x3F)
        ));
        output.push_back(static_cast<char>(0x80 | (codepoint & 0x3F)));
    } else {
        output.push_back(static_cast<char>(0xF0 | (codepoint >> 18)));
        output.push_back(static_cast<char>(
            0x80 | ((codepoint >> 12) & 0x3F)
        ));
        output.push_back(static_cast<char>(
            0x80 | ((codepoint >> 6) & 0x3F)
        ));
        output.push_back(static_cast<char>(0x80 | (codepoint & 0x3F)));
    }
}

inline Rune decode_utf8(std::string_view text, u32 i) {
    const u8 c0 = static_cast<u8>(text[i]);

    if (c0 < 0x80) {
        return {c0, 1};
    }

    if (
        c0 >= 0xC2 && c0 <= 0xDF &&
        i + 1 < text.size() &&
        (static_cast<u8>(text[i + 1]) & 0xC0) == 0x80
    ) {
        return {
            static_cast<char32_t>(
                ((c0 & 0x1F) << 6) |
                (static_cast<u8>(text[i + 1]) & 0x3F)
            ),
            2
        };
    }

    if (
        (c0 & 0xF0) == 0xE0 &&
        i + 2 < text.size() &&
        (static_cast<u8>(text[i + 1]) & 0xC0) == 0x80 &&
        (static_cast<u8>(text[i + 2]) & 0xC0) == 0x80
    ) {
        const char32_t codepoint = static_cast<char32_t>(
                ((c0 & 0x0F) << 12) |
                ((static_cast<u8>(text[i + 1]) & 0x3F) << 6) |
                (static_cast<u8>(text[i + 2]) & 0x3F)
            );

        if (
            codepoint >= 0x800 &&
            !(codepoint >= 0xD800 && codepoint <= 0xDFFF)
        ) {
            return {codepoint, 3};
        }
    }

    if (
        c0 >= 0xF0 && c0 <= 0xF4 &&
        i + 3 < text.size() &&
        (static_cast<u8>(text[i + 1]) & 0xC0) == 0x80 &&
        (static_cast<u8>(text[i + 2]) & 0xC0) == 0x80 &&
        (static_cast<u8>(text[i + 3]) & 0xC0) == 0x80
    ) {
        const char32_t codepoint = static_cast<char32_t>(
                ((c0 & 0x07) << 18) |
                ((static_cast<u8>(text[i + 1]) & 0x3F) << 12) |
                ((static_cast<u8>(text[i + 2]) & 0x3F) << 6) |
                (static_cast<u8>(text[i + 3]) & 0x3F)
            );

        if (codepoint >= 0x10000 && codepoint <= 0x10FFFF) {
            return {codepoint, 4};
        }
    }

    return {U'\uFFFD', 1, false};
}

inline int rune_cell_width(char32_t codepoint) {
    if (codepoint >= U' ' && codepoint <= U'~') {
        return 1;
    }

    if (codepoint < U' ' || codepoint == U'\x7F') {
        return -1;
    }

    if (
        codepoint > U'\U0010FFFF' ||
        (codepoint >= 0xD800 && codepoint <= 0xDFFF) ||
        unicode_interval_contains(
            codepoint,
            kUnicodeControlIntervals
        )
    ) {
        return -1;
    }

    if (unicode_interval_contains(
            codepoint,
            kUnicodeZeroWidthIntervals
        )) {
        return 0;
    }

    return unicode_interval_contains(codepoint, kUnicodeWideIntervals)
        ? 2
        : 1;
}

inline bool unicode_mark(char32_t codepoint) {
    if (codepoint <= 0x7F) {
        return false;
    }

    return unicode_interval_contains(codepoint, kUnicodeMarkIntervals);
}

inline bool unicode_whitespace(char32_t codepoint) {
    if (codepoint <= 0x7F) {
        return
            (codepoint >= U'\t' && codepoint <= U'\r') ||
            (codepoint >= 0x1C && codepoint <= U' ');
    }

    return unicode_interval_contains(
        codepoint,
        kUnicodeWhitespaceIntervals
    );
}

inline DisplayRune display_rune(char32_t codepoint) {
    const int width = rune_cell_width(codepoint);

    return width < 0
        ? DisplayRune{U'\uFFFD', 1}
        : DisplayRune{codepoint, width};
}

inline bool valid_utf8_display_text(
    std::string_view text,
    bool require_combining_anchor = true
) {
    bool anchored = false;

    for (u32 byte = 0; byte < text.size();) {
        const Rune rune = decode_utf8(text, byte);

        if (!rune.valid) {
            return false;
        }

        if (
            rune.codepoint == U'\n' ||
            rune.codepoint == U'\r' ||
            rune.codepoint == U'\t'
        ) {
            anchored = false;
            byte += rune.bytes;
            continue;
        }

        if (rune_cell_width(rune.codepoint) < 0) {
            return false;
        }

        if (unicode_mark(rune.codepoint)) {
            if (require_combining_anchor && !anchored) {
                return false;
            }
        } else {
            anchored = !unicode_whitespace(rune.codepoint);
        }

        byte += rune.bytes;
    }

    return true;
}
