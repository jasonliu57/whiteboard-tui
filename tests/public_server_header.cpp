#include "agent_server.hpp"

#include <type_traits>

static_assert(!std::is_copy_constructible_v<AgentServer>);
