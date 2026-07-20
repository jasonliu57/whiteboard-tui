#pragma once

#include "../types.hpp"

inline constexpr u64 kMaximumProjectBytes = 1024ULL * 1024ULL * 1024ULL;
inline constexpr u64 kMaximumProjectAllocationBytes =
    512ULL * 1024ULL * 1024ULL;
inline constexpr u32 kMaximumProjectSlots = 10'000'000;
inline constexpr u32 kMaximumProjectItems = 50'000'000;
inline constexpr u32 kMaximumProjectStringBytes = 64U * 1024U * 1024U;
