cmake_minimum_required(VERSION 4.3)

project(whiteboard_tui_install_consumer LANGUAGES CXX)

find_package(whiteboard-tui 2.0 CONFIG REQUIRED)

add_executable(whiteboard_install_consumer main.cpp)
target_compile_features(whiteboard_install_consumer PRIVATE cxx_std_20)
target_link_libraries(
    whiteboard_install_consumer
    PRIVATE
        whiteboard::core
        whiteboard::io
        whiteboard::render
        whiteboard::agent
        whiteboard::tui
)
