#include "tui/entry.hpp"

#include <type_traits>

static_assert(std::is_function_v<decltype(run_whiteboard_tui)>);
