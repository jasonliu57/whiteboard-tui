foreach(required SOURCE_DIR BINARY_DIR GENERATOR CONFIG)
    if(NOT DEFINED ${required} OR "${${required}}" STREQUAL "")
        message(FATAL_ERROR "missing ${required}")
    endif()
endforeach()

cmake_path(NORMAL_PATH BINARY_DIR OUTPUT_VARIABLE normalized_binary)
string(RANDOM LENGTH 16 ALPHABET 0123456789abcdef run_id)
set(test_root "${normalized_binary}/test-work/install-${run_id}")
set(normalized_install "${test_root}/prefix")
set(normalized_consumer "${test_root}/consumer")
cmake_path(IS_PREFIX normalized_binary "${normalized_install}" NORMALIZE install_is_scoped)
cmake_path(IS_PREFIX normalized_binary "${normalized_consumer}" NORMALIZE consumer_is_scoped)

if(NOT install_is_scoped OR NOT consumer_is_scoped)
    message(FATAL_ERROR "install smoke paths must remain under the build tree")
endif()

file(MAKE_DIRECTORY "${test_root}")

set(consumer_prefix "${normalized_install}")

if(DEFINED DEPENDENCY_PREFIX AND NOT "${DEPENDENCY_PREFIX}" STREQUAL "")
    cmake_path(NORMAL_PATH DEPENDENCY_PREFIX OUTPUT_VARIABLE normalized_dependency)

    if(EXISTS "${normalized_dependency}")
        list(APPEND consumer_prefix "${normalized_dependency}")
    endif()
endif()

execute_process(
    COMMAND
        "${CMAKE_COMMAND}" --install "${normalized_binary}"
        --prefix "${normalized_install}" --config "${CONFIG}"
    RESULT_VARIABLE install_result
    OUTPUT_VARIABLE install_output
    ERROR_VARIABLE install_error
)
if(NOT install_result EQUAL 0)
    message(FATAL_ERROR "install failed:\n${install_output}\n${install_error}")
endif()

foreach(installed_tool IN ITEMS whiteboard_tui whiteboardctl whiteboard-inspect)
    if(NOT EXISTS "${normalized_install}/bin/${installed_tool}")
        message(FATAL_ERROR "installed executable is missing: ${installed_tool}")
    endif()
endforeach()

foreach(private_header IN ITEMS
    app.hpp
    formats/internal.hpp
    formats/text_render.hpp
    languages/cpp.hpp
    languages/markdown.hpp
    platform/posix_fd.hpp
    storage/project.hpp
    storage/card_content.hpp
    tui/all.hpp
)
    if(EXISTS "${normalized_install}/include/whiteboard/${private_header}")
        message(FATAL_ERROR "private header was installed: ${private_header}")
    endif()
endforeach()

execute_process(
    COMMAND
        "${CMAKE_COMMAND}"
        -S "${SOURCE_DIR}/tests/install_consumer"
        -B "${normalized_consumer}"
        -G "${GENERATOR}"
        "-DCMAKE_PREFIX_PATH=${consumer_prefix}"
        "-DCMAKE_BUILD_TYPE=${CONFIG}"
    RESULT_VARIABLE configure_result
    OUTPUT_VARIABLE configure_output
    ERROR_VARIABLE configure_error
)
if(NOT configure_result EQUAL 0)
    message(FATAL_ERROR "consumer configure failed:\n${configure_output}\n${configure_error}")
endif()

execute_process(
    COMMAND
        "${CMAKE_COMMAND}" --build "${normalized_consumer}"
        --config "${CONFIG}" --parallel 2
    RESULT_VARIABLE build_result
    OUTPUT_VARIABLE build_output
    ERROR_VARIABLE build_error
)
if(NOT build_result EQUAL 0)
    message(FATAL_ERROR "consumer build failed:\n${build_output}\n${build_error}")
endif()

execute_process(
    COMMAND "${normalized_consumer}/whiteboard_install_consumer"
    RESULT_VARIABLE run_result
    OUTPUT_VARIABLE run_output
    ERROR_VARIABLE run_error
)
if(NOT run_result EQUAL 0)
    message(FATAL_ERROR "consumer run failed:\n${run_output}\n${run_error}")
endif()

cmake_path(IS_PREFIX normalized_binary "${test_root}" NORMALIZE cleanup_is_scoped)
if(NOT cleanup_is_scoped)
    message(FATAL_ERROR "install smoke cleanup escaped the build tree")
endif()
file(REMOVE_RECURSE "${test_root}")
