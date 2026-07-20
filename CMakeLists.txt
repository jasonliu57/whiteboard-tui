cmake_minimum_required(VERSION 4.3)

project(whiteboard_tui VERSION 2.0.0 LANGUAGES C CXX)

if(WIN32 AND NOT EMSCRIPTEN)
    message(FATAL_ERROR "native Windows is unsupported; configure inside WSL2")
endif()

if(NOT UNIX AND NOT EMSCRIPTEN)
    message(FATAL_ERROR "whiteboardTUI requires a POSIX system")
endif()

include(CTest)
include(GNUInstallDirs)
include(CMakePackageConfigHelpers)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()

if(EMSCRIPTEN)
    include(cmake/web-dependencies.cmake)
else()
    find_package(absl CONFIG REQUIRED)
    find_package(Freetype REQUIRED)
    find_package(PNG REQUIRED)

    get_target_property(
        WHITEBOARD_ABSL_INCLUDE_DIRECTORIES
        absl::config
        INTERFACE_INCLUDE_DIRECTORIES
    )
    set(WHITEBOARD_ABSL_VERSION "")
    foreach(include_directory IN LISTS WHITEBOARD_ABSL_INCLUDE_DIRECTORIES)
        set(absl_config_header "${include_directory}/absl/base/config.h")

        if(EXISTS "${absl_config_header}")
            file(
                STRINGS "${absl_config_header}"
                absl_version_definition
                REGEX "^#define ABSL_LTS_RELEASE_VERSION [0-9]+$"
            )

            if(absl_version_definition)
                string(
                    REGEX REPLACE ".* ([0-9]+)$" "\\1"
                    WHITEBOARD_ABSL_VERSION
                    "${absl_version_definition}"
                )
                break()
            endif()
        endif()
    endforeach()

    if(NOT WHITEBOARD_ABSL_VERSION)
        message(FATAL_ERROR "unable to determine the Abseil LTS ABI version")
    endif()

endif()

option(
    WHITEBOARD_BUILD_STRESS
    "Build the standalone stress benchmark"
    OFF
)
option(
    WHITEBOARD_WARNINGS_AS_ERRORS
    "Treat project C++ warnings as errors"
    OFF
)
option(
    WHITEBOARD_ENABLE_SANITIZERS
    "Enable AddressSanitizer and signed-integer-overflow checks"
    OFF
)
set(
    WHITEBOARD_PACKAGE_PLATFORM
    "${CMAKE_SYSTEM_NAME}-${CMAKE_SYSTEM_PROCESSOR}"
    CACHE STRING
    "Platform label used in the generated release archive name"
)

if(NOT WHITEBOARD_PACKAGE_PLATFORM MATCHES "^[A-Za-z0-9._+-]+$")
    message(FATAL_ERROR "WHITEBOARD_PACKAGE_PLATFORM contains unsafe characters")
endif()

add_library(
    whiteboard_tree_sitter STATIC
    vendor/tree-sitter/lib/src/lib.c
)
add_library(whiteboard::tree_sitter ALIAS whiteboard_tree_sitter)
set_target_properties(
    whiteboard_tree_sitter
    PROPERTIES
        EXPORT_NAME tree_sitter
        C_VISIBILITY_PRESET hidden
        POSITION_INDEPENDENT_CODE ON
)
target_include_directories(
    whiteboard_tree_sitter
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/vendor/tree-sitter/lib/include>
        $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}/whiteboard/vendor>
    PRIVATE
        vendor/tree-sitter/lib/src
)
target_compile_features(whiteboard_tree_sitter PRIVATE c_std_11)
target_compile_definitions(
    whiteboard_tree_sitter
    PRIVATE
        _POSIX_C_SOURCE=200112L
        _DEFAULT_SOURCE
        _BSD_SOURCE
        _DARWIN_C_SOURCE
)

function(
    add_whiteboard_tree_sitter_grammar
    target
    export_name
    source_directory
    binding_directory
)
    add_library(
        ${target} STATIC
        ${source_directory}/parser.c
        ${source_directory}/scanner.c
    )
    set_target_properties(
        ${target}
        PROPERTIES
            EXPORT_NAME ${export_name}
            POSITION_INDEPENDENT_CODE ON
    )
    target_include_directories(
        ${target}
        PUBLIC
            $<BUILD_INTERFACE:${binding_directory}>
            $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}/whiteboard/vendor>
        PRIVATE
            ${source_directory}
    )
    target_compile_features(${target} PRIVATE c_std_11)
    target_compile_definitions(
        ${target}
        PRIVATE $<$<CONFIG:Debug>:TREE_SITTER_DEBUG>
    )
endfunction()

add_whiteboard_tree_sitter_grammar(
    whiteboard_tree_sitter_markdown
    tree_sitter_markdown
    ${CMAKE_CURRENT_SOURCE_DIR}/vendor/tree-sitter-markdown/tree-sitter-markdown/src
    ${CMAKE_CURRENT_SOURCE_DIR}/vendor/tree-sitter-markdown/tree-sitter-markdown/bindings/c
)
add_library(
    whiteboard::tree_sitter_markdown
    ALIAS whiteboard_tree_sitter_markdown
)

add_whiteboard_tree_sitter_grammar(
    whiteboard_tree_sitter_markdown_inline
    tree_sitter_markdown_inline
    ${CMAKE_CURRENT_SOURCE_DIR}/vendor/tree-sitter-markdown/tree-sitter-markdown-inline/src
    ${CMAKE_CURRENT_SOURCE_DIR}/vendor/tree-sitter-markdown/tree-sitter-markdown-inline/bindings/c
)
add_library(
    whiteboard::tree_sitter_markdown_inline
    ALIAS whiteboard_tree_sitter_markdown_inline
)

foreach(vendored_header IN ITEMS
    vendor/tree-sitter-markdown/tree-sitter-markdown/bindings/c/tree_sitter/tree-sitter-markdown.h
    vendor/tree-sitter-markdown/tree-sitter-markdown-inline/bindings/c/tree_sitter/tree-sitter-markdown-inline.h
)
    if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/${vendored_header}")
        message(FATAL_ERROR "missing vendored Tree-sitter header: ${vendored_header}")
    endif()
endforeach()

add_library(
    tree_sitter_cpp STATIC
    vendor/tree-sitter-cpp/src/parser.c
    vendor/tree-sitter-cpp/src/scanner.c
)

target_include_directories(
    tree_sitter_cpp
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/vendor/tree-sitter-cpp/bindings/c>
        $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}/whiteboard/vendor>
    PRIVATE
        vendor/tree-sitter-cpp/src
)

target_compile_features(tree_sitter_cpp PRIVATE c_std_11)

function(whiteboard_enable_warnings target)
    target_compile_options(
        ${target}
        PRIVATE
            $<$<COMPILE_LANGUAGE:CXX>:-Wall;-Wextra;-pedantic>
    )

    if(WHITEBOARD_WARNINGS_AS_ERRORS)
        target_compile_options(
            ${target}
            PRIVATE $<$<COMPILE_LANGUAGE:CXX>:-Werror>
        )
    endif()

    if(WHITEBOARD_ENABLE_SANITIZERS)
        # System Abseil is built without sanitizer-only Swiss-table generation
        # fields; keep its header ABI identical while instrumenting our code.
        target_compile_definitions(${target} PRIVATE NDEBUG_SANITIZER)
        target_compile_options(
            ${target}
            PRIVATE $<$<COMPILE_LANGUAGE:CXX>:-fsanitize=address,signed-integer-overflow;-fno-omit-frame-pointer>
        )
        get_target_property(whiteboard_target_type ${target} TYPE)
        if(whiteboard_target_type STREQUAL "STATIC_LIBRARY")
            # An installed sanitizer-instrumented archive still needs the
            # runtime when a downstream executable performs the final link.
            target_link_options(
                ${target}
                INTERFACE -fsanitize=address,signed-integer-overflow
            )
        else()
            target_link_options(
                ${target}
                PRIVATE -fsanitize=address,signed-integer-overflow
            )
        endif()
    endif()
endfunction()

add_library(
    whiteboard_core STATIC
    src/core/board_document.cpp
    src/formats/code.cpp
    src/formats/csv.cpp
    src/formats/draw.cpp
    src/formats/folder.cpp
    src/formats/markdown.cpp
    src/formats/plain_text_note.cpp
    src/formats/registry.cpp
    src/formats/text_art.cpp
    src/formats/text_edit.cpp
    src/formats/todo.cpp
    src/text/buffer.cpp
    src/text/style.cpp
    src/text/syntax.cpp
)
add_library(whiteboard::core ALIAS whiteboard_core)
set_target_properties(whiteboard_core PROPERTIES EXPORT_NAME core)
target_include_directories(
    whiteboard_core
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/src>
        $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}/whiteboard>
)
target_compile_features(whiteboard_core PUBLIC cxx_std_20)
target_link_libraries(
    whiteboard_core
    PUBLIC
        absl::btree
        absl::flat_hash_map
        absl::flat_hash_set
        absl::inlined_vector
        whiteboard_tree_sitter
        whiteboard_tree_sitter_markdown
        whiteboard_tree_sitter_markdown_inline
        tree_sitter_cpp
)
whiteboard_enable_warnings(whiteboard_core)

add_library(whiteboard_codec STATIC src/storage/io.cpp)
add_library(whiteboard::codec ALIAS whiteboard_codec)
set_target_properties(whiteboard_codec PROPERTIES EXPORT_NAME codec)
target_compile_features(whiteboard_codec PUBLIC cxx_std_20)
target_link_libraries(whiteboard_codec PUBLIC whiteboard_core)
whiteboard_enable_warnings(whiteboard_codec)

add_library(whiteboard_board_render STATIC src/render/board.cpp src/render/overview.cpp)
add_library(whiteboard::board_render ALIAS whiteboard_board_render)
set_target_properties(whiteboard_board_render PROPERTIES EXPORT_NAME board_render)
target_compile_features(whiteboard_board_render PUBLIC cxx_std_20)
target_link_libraries(whiteboard_board_render PUBLIC whiteboard_core)
whiteboard_enable_warnings(whiteboard_board_render)

if(EMSCRIPTEN)
    include(cmake/web.cmake)
    return()
endif()

add_library(
    whiteboard_io STATIC
    src/storage/atomic_file.cpp
    src/storage/native.cpp
    src/storage/folder_export.cpp
    src/platform/native/app_io.cpp
    src/verification/canonical_snapshot.cpp
)
add_library(whiteboard::io ALIAS whiteboard_io)
set_target_properties(whiteboard_io PROPERTIES EXPORT_NAME io)
target_compile_features(whiteboard_io PUBLIC cxx_std_20)
target_link_libraries(whiteboard_io PUBLIC whiteboard_codec)
whiteboard_enable_warnings(whiteboard_io)

add_library(
    whiteboard_render STATIC
    src/render/font_rasterizer.cpp
    src/render/screenshot.cpp
    src/render/thumbnail.cpp
)
add_library(whiteboard::render ALIAS whiteboard_render)
set_target_properties(whiteboard_render PROPERTIES EXPORT_NAME render)
target_compile_features(whiteboard_render PUBLIC cxx_std_20)
target_link_libraries(whiteboard_render PUBLIC
    whiteboard_board_render Freetype::Freetype PNG::PNG)
whiteboard_enable_warnings(whiteboard_render)

add_library(
    whiteboard_agent STATIC
    src/agent_protocol.cpp
    src/agent_server.cpp
)
add_library(whiteboard::agent ALIAS whiteboard_agent)
set_target_properties(whiteboard_agent PROPERTIES EXPORT_NAME agent)
target_include_directories(
    whiteboard_agent
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/src>
        $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}/whiteboard>
)
target_compile_features(whiteboard_agent PUBLIC cxx_std_20)
whiteboard_enable_warnings(whiteboard_agent)

add_library(
    whiteboard_tui_runtime STATIC
    src/tui/entry.cpp
)
add_library(whiteboard::tui ALIAS whiteboard_tui_runtime)
set_target_properties(whiteboard_tui_runtime PROPERTIES EXPORT_NAME tui)
target_link_libraries(
    whiteboard_tui_runtime
    PUBLIC
        whiteboard_core
        whiteboard_io
        whiteboard_render
        whiteboard_agent
)
target_compile_features(whiteboard_tui_runtime PUBLIC cxx_std_20)
whiteboard_enable_warnings(whiteboard_tui_runtime)

add_executable(whiteboard_tui src/main.cpp)
add_executable(whiteboardctl src/whiteboardctl.cpp)
add_executable(whiteboard-inspect src/whiteboard_inspect.cpp)

target_link_libraries(
    whiteboard_tui
    PRIVATE
        whiteboard_tui_runtime
)
target_link_libraries(
    whiteboardctl
    PRIVATE whiteboard_agent whiteboard_io
)
target_link_libraries(whiteboard-inspect PRIVATE whiteboard_io)

target_compile_features(whiteboard_tui PRIVATE cxx_std_20)
target_compile_features(whiteboardctl PRIVATE cxx_std_20)
target_compile_features(whiteboard-inspect PRIVATE cxx_std_20)
whiteboard_enable_warnings(whiteboard_tui)
whiteboard_enable_warnings(whiteboardctl)
whiteboard_enable_warnings(whiteboard-inspect)

if(WHITEBOARD_BUILD_STRESS OR BUILD_TESTING)
    add_executable(
        whiteboard_stress
        tools/stress_benchmark.cpp
    )

    target_link_libraries(
        whiteboard_stress
        PRIVATE
            whiteboard_core
            whiteboard_io
            whiteboard_render
    )

    target_compile_features(
        whiteboard_stress
        PRIVATE
            cxx_std_20
    )

    target_compile_definitions(
        whiteboard_stress
        PRIVATE
            WHITEBOARD_BUILD_TYPE="${CMAKE_BUILD_TYPE}"
            WHITEBOARD_COMPILER_ID="${CMAKE_CXX_COMPILER_ID}"
            WHITEBOARD_COMPILER_VERSION="${CMAKE_CXX_COMPILER_VERSION}"
            WHITEBOARD_SYSTEM_NAME="${CMAKE_SYSTEM_NAME}"
            WHITEBOARD_SYSTEM_PROCESSOR="${CMAKE_SYSTEM_PROCESSOR}"
    )

    whiteboard_enable_warnings(whiteboard_stress)
endif()

if(BUILD_TESTING)
    set(WHITEBOARD_TEST_DEPENDENCY_PREFIX "")

    if(VCPKG_INSTALLED_DIR AND VCPKG_TARGET_TRIPLET)
        set(
            WHITEBOARD_TEST_DEPENDENCY_PREFIX
            "${VCPKG_INSTALLED_DIR}/${VCPKG_TARGET_TRIPLET}"
        )
    endif()

    if(APPLE)
        set(WHITEBOARD_TEST_UTF8_LOCALE "en_US.UTF-8")
    else()
        set(WHITEBOARD_TEST_UTF8_LOCALE "C.UTF-8")
    endif()

    function(add_whiteboard_header_check check_name source library)
        add_library(${check_name} OBJECT ${source})
        target_link_libraries(${check_name} PRIVATE ${library})
        target_compile_features(${check_name} PRIVATE cxx_std_20)
        whiteboard_enable_warnings(${check_name})
    endfunction()

    add_whiteboard_header_check(
        public_core_header_check
        tests/public_core_header.cpp
        whiteboard_core
    )
    add_whiteboard_header_check(
        public_render_header_check
        tests/public_render_header.cpp
        whiteboard_render
    )
    add_whiteboard_header_check(
        public_format_header_check
        tests/public_format_header.cpp
        whiteboard_core
    )
    add_whiteboard_header_check(
        public_text_buffer_header_check
        tests/public_text_buffer_header.cpp
        whiteboard_core
    )
    add_whiteboard_header_check(
        public_text_style_header_check
        tests/public_text_style_header.cpp
        whiteboard_core
    )
    add_whiteboard_header_check(
        public_text_syntax_header_check
        tests/public_text_syntax_header.cpp
        whiteboard_core
    )
    add_whiteboard_header_check(
        public_atomic_header_check
        tests/public_atomic_header.cpp
        whiteboard_io
    )
    add_whiteboard_header_check(
        public_folder_header_check
        tests/public_folder_header.cpp
        whiteboard_io
    )
    add_whiteboard_header_check(
        public_storage_api_header_check
        tests/public_storage_api_header.cpp
        whiteboard_io
    )
    add_whiteboard_header_check(
        public_snapshot_header_check
        tests/public_snapshot_header.cpp
        whiteboard_io
    )
    add_whiteboard_header_check(
        public_screen_header_check
        tests/public_screen_header.cpp
        whiteboard_render
    )
    add_whiteboard_header_check(
        public_screenshot_header_check
        tests/public_screenshot_header.cpp
        whiteboard_render
    )
    add_whiteboard_header_check(
        public_thumbnail_header_check
        tests/public_thumbnail_header.cpp
        whiteboard_render
    )
    add_whiteboard_header_check(
        public_protocol_header_check
        tests/public_protocol_header.cpp
        whiteboard_agent
    )
    add_whiteboard_header_check(
        public_server_header_check
        tests/public_server_header.cpp
        whiteboard_agent
    )
    add_whiteboard_header_check(
        public_tui_header_check
        tests/public_tui_header.cpp
        whiteboard_tui_runtime
    )

    add_executable(
        whiteboard_tests
        tests/whiteboard_tests.cpp
    )

    target_link_libraries(
        whiteboard_tests
        PRIVATE
            whiteboard_core
            whiteboard_io
            whiteboard_render
            whiteboard_agent
    )

    target_compile_features(whiteboard_tests PRIVATE cxx_std_20)
    whiteboard_enable_warnings(whiteboard_tests)

    add_executable(whiteboard_web_fixture tests/web_fixture.cpp)
    target_link_libraries(whiteboard_web_fixture PRIVATE whiteboard_io whiteboard_board_render)
    whiteboard_enable_warnings(whiteboard_web_fixture)

    file(
        STRINGS tests/whiteboard_test_cases.def
        WHITEBOARD_CPP_TEST_CASES
        REGEX "^WHITEBOARD_TEST_CASE"
    )
    foreach(case_entry IN LISTS WHITEBOARD_CPP_TEST_CASES)
        string(
            REGEX REPLACE
            "^WHITEBOARD_TEST_CASE\\(\"([^\"]+)\",.*$"
            "\\1"
            case_name
            "${case_entry}"
        )
        string(REPLACE "." "_" ctest_name "${case_name}")
        add_test(
            NAME whiteboard_${ctest_name}
            COMMAND whiteboard_tests --case ${case_name}
        )
        set_tests_properties(
            whiteboard_${ctest_name}
            PROPERTIES
                ENVIRONMENT "LC_ALL=${WHITEBOARD_TEST_UTF8_LOCALE}"
                LABELS "cpp;unit"
                TIMEOUT 15
        )
    endforeach()

    file(
        STRINGS benchmarks/stress_scenarios.def
        WHITEBOARD_STRESS_SCENARIOS
        REGEX "^WHITEBOARD_STRESS_SCENARIO"
    )
    foreach(scenario_entry IN LISTS WHITEBOARD_STRESS_SCENARIOS)
        string(
            REGEX REPLACE
            "^WHITEBOARD_STRESS_SCENARIO\\(\"([^\"]+)\",.*$"
            "\\1"
            scenario
            "${scenario_entry}"
        )
        string(REPLACE "-" "_" scenario_name "${scenario}")
        add_test(
            NAME whiteboard_stress_${scenario_name}
            COMMAND whiteboard_stress --quick --scenario ${scenario}
        )
        set_tests_properties(
            whiteboard_stress_${scenario_name}
            PROPERTIES
                ENVIRONMENT "LC_ALL=${WHITEBOARD_TEST_UTF8_LOCALE}"
                LABELS "benchmark;quick"
                TIMEOUT 30
        )
    endforeach()

    find_package(Python3 COMPONENTS Interpreter REQUIRED)
    function(whiteboard_list_python_tests output_variable)
        execute_process(
            COMMAND
                ${Python3_EXECUTABLE} -B tests/list_python_tests.py ${ARGN}
            WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
            RESULT_VARIABLE python_test_list_result
            OUTPUT_VARIABLE python_test_list_output
            ERROR_VARIABLE python_test_list_error
        )
        if(NOT python_test_list_result EQUAL 0)
            message(FATAL_ERROR "Python test listing failed:\n${python_test_list_error}")
        endif()
        string(REPLACE "\n" ";" python_test_lines "${python_test_list_output}")
        set(${output_variable} "${python_test_lines}" PARENT_SCOPE)
    endfunction()

    function(add_whiteboard_python_tests label)
        whiteboard_list_python_tests(python_test_lines ${ARGN})
        foreach(test_line IN LISTS python_test_lines)
            if(test_line MATCHES "^([^\t]+)\t(.+)$")
                set(source_path "${CMAKE_MATCH_1}")
                set(test_selector "${CMAKE_MATCH_2}")
                set(test_suffix "${source_path}_${test_selector}")
                string(REGEX REPLACE "[^A-Za-z0-9_]+" "_" test_suffix "${test_suffix}")
                add_test(
                    NAME python_${test_suffix}
                    COMMAND
                        ${Python3_EXECUTABLE} -B ${source_path} ${test_selector}
                )
                set_tests_properties(
                    python_${test_suffix}
                    PROPERTIES
                        WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
                        ENVIRONMENT "PYTHONDONTWRITEBYTECODE=1;PYTHONPATH=${CMAKE_CURRENT_SOURCE_DIR};LC_ALL=${WHITEBOARD_TEST_UTF8_LOCALE}"
                        LABELS "python;${label}"
                        TIMEOUT 30
                )
            endif()
        endforeach()
    endfunction()

    function(add_whiteboard_python_script_tests prefix source_path label timeout)
        cmake_parse_arguments(
            TEST
            ""
            "RESOURCE_LOCK"
            "ARGS;ENVIRONMENT"
            ${ARGN}
        )
        whiteboard_list_python_tests(python_test_lines ${source_path})
        foreach(test_line IN LISTS python_test_lines)
            if(test_line MATCHES "^[^\t]+\t(.+)$")
                set(test_selector "${CMAKE_MATCH_1}")
                string(
                    REGEX REPLACE
                    "[^A-Za-z0-9_]+"
                    "_"
                    test_suffix
                    "${test_selector}"
                )
                set(test_name "${prefix}_${test_suffix}")
                add_test(
                    NAME ${test_name}
                    COMMAND
                        ${Python3_EXECUTABLE} -B ${source_path}
                        ${TEST_ARGS}
                        ${test_selector}
                )
                set(test_environment
                    "PYTHONDONTWRITEBYTECODE=1"
                    "PYTHONPATH=${CMAKE_CURRENT_SOURCE_DIR}"
                    "LC_ALL=${WHITEBOARD_TEST_UTF8_LOCALE}"
                    ${TEST_ENVIRONMENT}
                )
                set_tests_properties(
                    ${test_name}
                    PROPERTIES
                        WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
                        ENVIRONMENT "${test_environment}"
                        LABELS "python;${label}"
                        TIMEOUT ${timeout}
                )
                if(TEST_RESOURCE_LOCK)
                    set_tests_properties(
                        ${test_name}
                        PROPERTIES RESOURCE_LOCK ${TEST_RESOURCE_LOCK}
                    )
                endif()
            endif()
        endforeach()
    endfunction()

    file(
        GLOB WHITEBOARD_TEXTART_TESTS
        CONFIGURE_DEPENDS
        RELATIVE "${CMAKE_CURRENT_SOURCE_DIR}"
        "tools/textart_notes/tests/test_*.py"
    )
    list(
        FILTER WHITEBOARD_TEXTART_TESTS
        EXCLUDE REGEX "test_entrypoints\\.py$"
    )
    file(
        GLOB WHITEBOARD_AUTOMATION_TESTS
        CONFIGURE_DEPENDS
        RELATIVE "${CMAKE_CURRENT_SOURCE_DIR}"
        "tools/whiteboard_automation/tests/test_*.py"
    )
    file(
        GLOB WHITEBOARD_SKILL_TESTS
        CONFIGURE_DEPENDS
        RELATIVE "${CMAKE_CURRENT_SOURCE_DIR}"
        ".agents/skills/whiteboard-markdown-mind-map/scripts/tests/test_*.py"
    )
    set(
        WHITEBOARD_CONFIGURE_TEST_SOURCES
        ${WHITEBOARD_TEXTART_TESTS}
        ${WHITEBOARD_AUTOMATION_TESTS}
        ${WHITEBOARD_SKILL_TESTS}
        tests/list_python_tests.py
        tests/test_benchmarks.py
        tests/test_native_files.py
        tests/test_whiteboardctl.py
        tools/textart_notes/integration_tests/test_materializer_board.py
        tools/textart_notes/render_note.py
    )
    list(
        TRANSFORM WHITEBOARD_CONFIGURE_TEST_SOURCES
        PREPEND "${CMAKE_CURRENT_SOURCE_DIR}/"
    )
    set_property(
        DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
        ${WHITEBOARD_CONFIGURE_TEST_SOURCES}
        "${CMAKE_CURRENT_SOURCE_DIR}/benchmarks/stress_scenarios.def"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/whiteboard_test_cases.def"
    )
    add_whiteboard_python_tests(
        unit
        ${WHITEBOARD_TEXTART_TESTS}
        ${WHITEBOARD_AUTOMATION_TESTS}
    )
    add_whiteboard_python_tests(skill ${WHITEBOARD_SKILL_TESTS})

    execute_process(
        COMMAND
            ${Python3_EXECUTABLE} -B
            tools/textart_notes/render_note.py --list-styles
        WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
        RESULT_VARIABLE renderer_registry_result
        OUTPUT_VARIABLE renderer_registry_output
        ERROR_VARIABLE renderer_registry_error
    )
    if(NOT renderer_registry_result EQUAL 0)
        message(FATAL_ERROR "renderer registry failed:\n${renderer_registry_error}")
    endif()
    string(REPLACE "\n" ";" renderer_registry_lines "${renderer_registry_output}")
    foreach(registry_line IN LISTS renderer_registry_lines)
        if(registry_line MATCHES "^([^\t]+)\t")
            set(renderer_style "${CMAKE_MATCH_1}")
            if(renderer_style STREQUAL "style")
                continue()
            endif()
            string(REPLACE "-" "_" renderer_method "${renderer_style}")
            add_test(
                NAME python_renderer_entrypoint_${renderer_method}
                COMMAND
                    ${Python3_EXECUTABLE} -B -m unittest -v
                    tools.textart_notes.tests.test_entrypoints.RendererEntrypointTests.test_${renderer_method}
            )
            set_tests_properties(
                python_renderer_entrypoint_${renderer_method}
                PROPERTIES
                    WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
                    ENVIRONMENT "PYTHONDONTWRITEBYTECODE=1;PYTHONPATH=${CMAKE_CURRENT_SOURCE_DIR};LC_ALL=${WHITEBOARD_TEST_UTF8_LOCALE}"
                    LABELS "python;unit;renderer-entrypoint"
                    TIMEOUT 15
            )
        endif()
    endforeach()

    add_test(
        NAME unicode_generated_tables_check
        COMMAND ${Python3_EXECUTABLE} -B tools/generate_unicode_width.py --check
    )

    add_test(
        NAME generated_contracts_check
        COMMAND ${Python3_EXECUTABLE} -B tools/generate_contract_schema.py --check
    )

    add_test(
        NAME documentation_links_check
        COMMAND ${Python3_EXECUTABLE} -B tests/check_documentation.py
    )

    add_test(
        NAME whiteboard_skill_structure_check
        COMMAND ${Python3_EXECUTABLE} -B tests/check_whiteboard_skill.py
    )

    add_test(
        NAME whiteboard_architecture_check
        COMMAND ${Python3_EXECUTABLE} -B tests/check_architecture.py
    )

    add_test(
        NAME unicode_cross_language_tests
        COMMAND
            ${Python3_EXECUTABLE} -B tests/compare_unicode_contract.py
            $<TARGET_FILE:whiteboard_tests>
    )

    add_whiteboard_python_script_tests(
        whiteboardctl
        tests/test_whiteboardctl.py
        "integration;whiteboardctl"
        10
        ARGS $<TARGET_FILE:whiteboardctl>
    )
    add_whiteboard_python_script_tests(
        whiteboard_benchmark
        tests/test_benchmarks.py
        "unit;benchmark"
        30
    )
    add_whiteboard_python_script_tests(
        whiteboard_native_files
        tests/test_native_files.py
        "integration;storage"
        30
        ARGS $<TARGET_FILE:whiteboard-inspect>
    )
    set_tests_properties(
        unicode_cross_language_tests
        PROPERTIES
            WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
            ENVIRONMENT "PYTHONDONTWRITEBYTECODE=1"
    )
    set_tests_properties(
        unicode_generated_tables_check
        PROPERTIES
            WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
            ENVIRONMENT "PYTHONDONTWRITEBYTECODE=1"
    )
    set_tests_properties(
        generated_contracts_check
        PROPERTIES
            WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
            ENVIRONMENT "PYTHONDONTWRITEBYTECODE=1"
    )
    set_tests_properties(
        documentation_links_check
        PROPERTIES
            WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
            ENVIRONMENT "PYTHONDONTWRITEBYTECODE=1"
    )
    set_tests_properties(
        whiteboard_skill_structure_check
        PROPERTIES
            WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
            ENVIRONMENT "PYTHONDONTWRITEBYTECODE=1"
    )
    set_tests_properties(
        whiteboard_architecture_check
        PROPERTIES
            WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
            ENVIRONMENT "PYTHONDONTWRITEBYTECODE=1"
    )

    add_whiteboard_python_script_tests(
        whiteboard_python_pty
        tools/textart_notes/integration_tests/test_materializer_board.py
        "integration;pty"
        60
        RESOURCE_LOCK whiteboard_tui
        ENVIRONMENT
            "WHITEBOARD_TEXTART_INTEGRATION=1"
            "WHITEBOARDCTL_BINARY=$<TARGET_FILE:whiteboardctl>"
            "WHITEBOARD_TUI_BINARY=$<TARGET_FILE:whiteboard_tui>"
            "WHITEBOARD_INSPECT_BINARY=$<TARGET_FILE:whiteboard-inspect>"
    )

    add_test(
        NAME whiteboard_install_package_tests
        COMMAND
            ${CMAKE_COMMAND}
            -DSOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}
            -DBINARY_DIR=${CMAKE_CURRENT_BINARY_DIR}
            -DGENERATOR=${CMAKE_GENERATOR}
            -DCONFIG=$<CONFIG>
            -DDEPENDENCY_PREFIX=${WHITEBOARD_TEST_DEPENDENCY_PREFIX}
            -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_install_package.cmake
    )
    set_tests_properties(
        whiteboard_install_package_tests
        PROPERTIES
            TIMEOUT 120
    )
endif()

install(
    TARGETS
        whiteboard_tree_sitter
        whiteboard_tree_sitter_markdown
        whiteboard_tree_sitter_markdown_inline
        tree_sitter_cpp
        whiteboard_core
        whiteboard_codec
        whiteboard_board_render
        whiteboard_io
        whiteboard_render
        whiteboard_agent
        whiteboard_tui_runtime
    EXPORT whiteboard-tui-targets
    ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
)
install(
    TARGETS whiteboard_tui whiteboardctl whiteboard-inspect
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
)
install(
    DIRECTORY src/
    DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}/whiteboard
    FILES_MATCHING
        PATTERN "*.hpp"
        PATTERN "app.hpp" EXCLUDE
        PATTERN "decimal.hpp" EXCLUDE
        PATTERN "formats/draw.hpp" EXCLUDE
        PATTERN "formats/internal.hpp" EXCLUDE
        PATTERN "formats/text_edit.hpp" EXCLUDE
        PATTERN "formats/text_render.hpp" EXCLUDE
        PATTERN "formats/validation.hpp" EXCLUDE
        PATTERN "languages/cpp.hpp" EXCLUDE
        PATTERN "languages/markdown.hpp" EXCLUDE
        PATTERN "platform" EXCLUDE
        PATTERN "render/image_internal.hpp" EXCLUDE
        PATTERN "storage/binary.hpp" EXCLUDE
        PATTERN "storage/card_content.hpp" EXCLUDE
        PATTERN "storage/project.hpp" EXCLUDE
        PATTERN "storage/string_view_stream.hpp" EXCLUDE
        PATTERN "storage/version.hpp" EXCLUDE
        PATTERN "tui" EXCLUDE
)
install(
    FILES src/tui/entry.hpp
    DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}/whiteboard/tui
)
install(
    FILES
        vendor/tree-sitter/lib/include/tree_sitter/api.h
        vendor/tree-sitter-markdown/tree-sitter-markdown/bindings/c/tree_sitter/tree-sitter-markdown.h
        vendor/tree-sitter-markdown/tree-sitter-markdown-inline/bindings/c/tree_sitter/tree-sitter-markdown-inline.h
    DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}/whiteboard/vendor/tree_sitter
)
install(
    FILES
        vendor/tree-sitter-cpp/bindings/c/tree-sitter-cpp.h
    DESTINATION
        ${CMAKE_INSTALL_INCLUDEDIR}/whiteboard/vendor
)
install(
    FILES README.md LICENSE
    DESTINATION ${CMAKE_INSTALL_DOCDIR}
)
install(
    DIRECTORY docs/
    DESTINATION ${CMAKE_INSTALL_DOCDIR}/docs
)
install(
    DIRECTORY benchmarks/
    DESTINATION ${CMAKE_INSTALL_DOCDIR}/benchmarks
)
install(
    FILES vendor/tree-sitter/LICENSE
    DESTINATION ${CMAKE_INSTALL_DOCDIR}
    RENAME tree-sitter-LICENSE
)
install(
    FILES vendor/tree-sitter-markdown/LICENSE
    DESTINATION ${CMAKE_INSTALL_DOCDIR}
    RENAME tree-sitter-markdown-LICENSE
)
install(
    FILES vendor/tree-sitter-cpp/LICENSE
    DESTINATION ${CMAKE_INSTALL_DOCDIR}
    RENAME tree-sitter-cpp-LICENSE
)
install(
    FILES vendor/tree-sitter/lib/src/unicode/LICENSE
    DESTINATION ${CMAKE_INSTALL_DOCDIR}
    RENAME tree-sitter-unicode-LICENSE
)

configure_package_config_file(
    cmake/whiteboard-tui-config.cmake.in
    ${CMAKE_CURRENT_BINARY_DIR}/whiteboard-tui-config.cmake
    INSTALL_DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/whiteboard-tui
)
write_basic_package_version_file(
    ${CMAKE_CURRENT_BINARY_DIR}/whiteboard-tui-config-version.cmake
    VERSION ${PROJECT_VERSION}
    COMPATIBILITY SameMajorVersion
)
install(
    FILES
        ${CMAKE_CURRENT_BINARY_DIR}/whiteboard-tui-config.cmake
        ${CMAKE_CURRENT_BINARY_DIR}/whiteboard-tui-config-version.cmake
    DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/whiteboard-tui
)
install(
    EXPORT whiteboard-tui-targets
    FILE whiteboard-tui-targets.cmake
    NAMESPACE whiteboard::
    DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/whiteboard-tui
)

set(CPACK_PACKAGE_NAME "whiteboard-tui")
set(CPACK_PACKAGE_VENDOR "whiteboardTUI contributors")
set(CPACK_PACKAGE_DESCRIPTION_SUMMARY "POSIX terminal infinite whiteboard")
set(CPACK_RESOURCE_FILE_README "${CMAKE_CURRENT_SOURCE_DIR}/README.md")
set(CPACK_RESOURCE_FILE_LICENSE "${CMAKE_CURRENT_SOURCE_DIR}/LICENSE")
set(CPACK_PACKAGE_VERSION "${PROJECT_VERSION}")
set(
    CPACK_PACKAGE_FILE_NAME
    "whiteboard-tui-${PROJECT_VERSION}-${WHITEBOARD_PACKAGE_PLATFORM}"
)
set(CPACK_GENERATOR "TGZ")
include(CPack)
