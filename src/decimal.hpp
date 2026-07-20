#pragma once

#include <charconv>
#include <cstddef>
#include <string>

template<class Integer>
inline void append_decimal(std::string& output, Integer value) {
    char digits[32];
    const auto result = std::to_chars(
        digits,
        digits + sizeof(digits),
        value
    );
    output.append(
        digits,
        static_cast<std::size_t>(result.ptr - digits)
    );
}
