#include "storage/atomic_file.hpp"

#include <type_traits>

static_assert(!std::is_copy_constructible_v<AtomicFileWriter>);
