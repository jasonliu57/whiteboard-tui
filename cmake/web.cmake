add_executable(whiteboard_web src/platform/web/entry.cpp)
target_link_libraries(whiteboard_web PRIVATE whiteboard_codec whiteboard_board_render)
target_compile_features(whiteboard_web PRIVATE cxx_std_20)
whiteboard_enable_warnings(whiteboard_web)
set_target_properties(whiteboard_web PROPERTIES
    OUTPUT_NAME whiteboard
    SUFFIX .mjs
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/web"
)
target_link_options(whiteboard_web PRIVATE
    --no-entry
    -fwasm-exceptions
    -sMODULARIZE=1
    -sEXPORT_ES6=1
    -sENVIRONMENT=worker,node
    -sFILESYSTEM=0
    -sALLOW_MEMORY_GROWTH=1
    -sINITIAL_MEMORY=67108864
    -sMAXIMUM_MEMORY=536870912
    -sSTACK_SIZE=2097152
    -sDYNAMIC_EXECUTION=0
    "-sEXPORTED_FUNCTIONS=['_malloc','_free']"
    "-sEXPORTED_RUNTIME_METHODS=['HEAPU8']"
)

set(web_license_directory "${CMAKE_BINARY_DIR}/web/licenses")
file(MAKE_DIRECTORY "${web_license_directory}")
get_filename_component(emscripten_directory "${CMAKE_CXX_COMPILER}" DIRECTORY)
configure_file("${emscripten_directory}/LICENSE" "${web_license_directory}/emscripten.txt" COPYONLY)
configure_file("${abseil_SOURCE_DIR}/LICENSE" "${web_license_directory}/abseil.txt" COPYONLY)
