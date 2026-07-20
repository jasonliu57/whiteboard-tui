include(FetchContent)

# Cross-compile the dependency with the same toolchain as the document core.
set(ABSL_BUILD_TESTING OFF CACHE BOOL "" FORCE)
set(ABSL_ENABLE_INSTALL OFF CACHE BOOL "" FORCE)
set(ABSL_PROPAGATE_CXX_STD ON CACHE BOOL "" FORCE)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_SCAN_FOR_MODULES OFF)
add_compile_options(-fwasm-exceptions)
FetchContent_Declare(abseil
    SYSTEM
    URL https://codeload.github.com/abseil/abseil-cpp/tar.gz/refs/tags/20260526.0
    URL_HASH SHA256=6e1aee535473414164bf83e4ebc40240dec71a4701f8a642d906e95bea1aea0c
)
FetchContent_MakeAvailable(abseil)
