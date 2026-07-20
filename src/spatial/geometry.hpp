#pragma once

#include <algorithm>
#include <cstdint>
#include <limits>

using u8  = std::uint8_t;
using u16 = std::uint16_t;
using u32 = std::uint32_t;
using u64 = std::uint64_t;
using i32 = std::int32_t;
using i64 = std::int64_t;

struct Pos {
    i64 x = 0;
    i64 y = 0;

    friend bool operator==(const Pos&, const Pos&) = default;
};

struct Extent {
    i32 width = 20;
    i32 height = 8;

    friend bool operator==(const Extent&, const Extent&) = default;
};

// Rectangles are half-open: [left, right) x [top, bottom).
struct Rect {
    i64 left = 0;
    i64 top = 0;
    i64 right = 0;
    i64 bottom = 0;

    friend bool operator==(const Rect&, const Rect&) = default;
};

inline bool valid_rect(Rect rect) noexcept {
    return rect.left < rect.right && rect.top < rect.bottom;
}

inline bool checked_add_i64(i64 first, i64 second, i64& result) {
    if (
        (second > 0 &&
         first > std::numeric_limits<i64>::max() - second) ||
        (second < 0 &&
         first < std::numeric_limits<i64>::min() - second)
    ) {
        return false;
    }

    result = first + second;
    return true;
}

inline bool checked_sub_i64(i64 first, i64 second, i64& result) {
    if (
        (second > 0 &&
         first < std::numeric_limits<i64>::min() + second) ||
        (second < 0 &&
         first > std::numeric_limits<i64>::max() + second)
    ) {
        return false;
    }

    result = first - second;
    return true;
}

inline i64 saturating_add_i64(i64 first, i64 second) {
    i64 result = 0;

    if (checked_add_i64(first, second, result)) {
        return result;
    }

    return second > 0
        ? std::numeric_limits<i64>::max()
        : std::numeric_limits<i64>::min();
}

inline i64 saturating_sub_i64(i64 first, i64 second) {
    i64 result = 0;

    if (checked_sub_i64(first, second, result)) {
        return result;
    }

    return second < 0
        ? std::numeric_limits<i64>::max()
        : std::numeric_limits<i64>::min();
}

inline bool checked_translate(Pos position, Pos delta, Pos& result) {
    return
        checked_add_i64(position.x, delta.x, result.x) &&
        checked_add_i64(position.y, delta.y, result.y);
}

inline bool checked_rect_at(
    Pos position,
    Extent extent,
    Rect& result
) {
    if (extent.width <= 0 || extent.height <= 0) {
        return false;
    }

    result.left = position.x;
    result.top = position.y;
    return
        checked_add_i64(position.x, extent.width, result.right) &&
        checked_add_i64(position.y, extent.height, result.bottom);
}

inline bool checked_point_rect(Pos position, Rect& result) {
    result.left = position.x;
    result.top = position.y;
    return
        checked_add_i64(position.x, 1, result.right) &&
        checked_add_i64(position.y, 1, result.bottom);
}

inline bool checked_selection_rect(
    Pos first,
    Pos second,
    Rect& result
) {
    result.left = std::min(first.x, second.x);
    result.top = std::min(first.y, second.y);
    return
        checked_add_i64(
            std::max(first.x, second.x),
            1,
            result.right
        ) &&
        checked_add_i64(
            std::max(first.y, second.y),
            1,
            result.bottom
        );
}

inline Rect rect_at(Pos position, Extent extent) {
    return {
        position.x,
        position.y,
        saturating_add_i64(position.x, extent.width),
        saturating_add_i64(position.y, extent.height),
    };
}

inline Rect point_rect(Pos position) {
    return {
        position.x,
        position.y,
        saturating_add_i64(position.x, 1),
        saturating_add_i64(position.y, 1),
    };
}

inline Rect selection_rect(Pos first, Pos second) {
    return {
        std::min(first.x, second.x),
        std::min(first.y, second.y),
        saturating_add_i64(std::max(first.x, second.x), 1),
        saturating_add_i64(std::max(first.y, second.y), 1),
    };
}

inline bool overlaps(Rect first, Rect second) {
    return
        first.left < second.right &&
        second.left < first.right &&
        first.top < second.bottom &&
        second.top < first.bottom;
}

inline bool contains(Rect outer, Rect inner) {
    return
        outer.left <= inner.left &&
        outer.top <= inner.top &&
        inner.right <= outer.right &&
        inner.bottom <= outer.bottom;
}

inline bool contains(Rect rect, Pos position) {
    return
        rect.left <= position.x &&
        position.x < rect.right &&
        rect.top <= position.y &&
        position.y < rect.bottom;
}

inline Rect unite(Rect first, Rect second) {
    return {
        std::min(first.left, second.left),
        std::min(first.top, second.top),
        std::max(first.right, second.right),
        std::max(first.bottom, second.bottom),
    };
}
