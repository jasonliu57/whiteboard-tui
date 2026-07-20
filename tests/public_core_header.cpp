#include "board_document.hpp"

#include <type_traits>

static_assert(!std::is_copy_constructible_v<BoardDocument>);
