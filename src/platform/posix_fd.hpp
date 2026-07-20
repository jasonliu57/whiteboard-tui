#pragma once

#include <cerrno>
#include <cstddef>
#include <cstring>
#include <fcntl.h>
#include <string_view>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

namespace whiteboard::platform {

struct LocalSocketAddress {
    sockaddr_un value{};
    socklen_t size = 0;
};

inline bool make_local_socket_address(
    std::string_view path,
    LocalSocketAddress& address
) noexcept {
    if (path.empty() || path.size() >= sizeof(sockaddr_un::sun_path)) {
        errno = path.empty() ? EINVAL : ENAMETOOLONG;
        return false;
    }

    address = {};
    address.value.sun_family = AF_UNIX;
    std::memcpy(address.value.sun_path, path.data(), path.size());
    address.value.sun_path[path.size()] = '\0';
    constexpr std::size_t prefix = offsetof(sockaddr_un, sun_path);
    const std::size_t size = prefix + path.size() + 1;

#if defined(__APPLE__)
    address.value.sun_len = static_cast<unsigned char>(size);
#endif

    address.size = static_cast<socklen_t>(size);
    return true;
}

inline int descriptor_flags(int descriptor, int command) noexcept {
    int result;

    do {
        result = ::fcntl(descriptor, command);
    } while (result < 0 && errno == EINTR);

    return result;
}

inline bool set_descriptor_flags(
    int descriptor,
    int command,
    int flags
) noexcept {
    int result;

    do {
        result = ::fcntl(descriptor, command, flags);
    } while (result < 0 && errno == EINTR);

    return result == 0;
}

inline bool set_nonblocking_close_on_exec(int descriptor) noexcept {
    const int file_flags = descriptor_flags(descriptor, F_GETFL);

    if (
        file_flags < 0 ||
        !set_descriptor_flags(
            descriptor,
            F_SETFL,
            file_flags | O_NONBLOCK
        )
    ) {
        return false;
    }

    const int descriptor_state = descriptor_flags(descriptor, F_GETFD);
    return
        descriptor_state >= 0 &&
        set_descriptor_flags(
            descriptor,
            F_SETFD,
            descriptor_state | FD_CLOEXEC
        );
}

inline bool set_no_sigpipe(int descriptor) noexcept {
#if defined(SO_NOSIGPIPE)
    constexpr int enabled = 1;
    int result;

    do {
        result = ::setsockopt(
            descriptor,
            SOL_SOCKET,
            SO_NOSIGPIPE,
            &enabled,
            sizeof(enabled)
        );
    } while (result < 0 && errno == EINTR);

    return result == 0;
#else
    static_cast<void>(descriptor);
    return true;
#endif
}

inline int no_signal_send_flags() noexcept {
#if defined(MSG_NOSIGNAL)
    return MSG_NOSIGNAL;
#else
    return 0;
#endif
}

inline int configure_local_stream(int descriptor) noexcept {
    if (descriptor < 0) {
        return -1;
    }

    if (
        set_nonblocking_close_on_exec(descriptor) &&
        set_no_sigpipe(descriptor)
    ) {
        return descriptor;
    }

    const int error = errno;
    ::close(descriptor);
    errno = error;
    return -1;
}

inline int open_local_stream() noexcept {
    return configure_local_stream(::socket(AF_UNIX, SOCK_STREAM, 0));
}

inline int accept_local_stream(int listener) noexcept {
    return configure_local_stream(::accept(listener, nullptr, nullptr));
}

} // namespace whiteboard::platform
