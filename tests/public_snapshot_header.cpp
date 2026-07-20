#include "verification/canonical_snapshot.hpp"

#include <type_traits>

static_assert(std::is_default_constructible_v<
    whiteboard::verification::CanonicalSnapshotCursor
>);
