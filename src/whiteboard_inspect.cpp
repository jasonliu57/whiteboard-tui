#include "formats/registry.hpp"
#include "storage/native.hpp"
#include "storage/atomic_file.hpp"
#include "verification/canonical_snapshot.hpp"

#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <string>
#include <string_view>
#include <system_error>

namespace {

void usage() {
    std::cerr <<
        "usage:\n"
        "  whiteboard-inspect snapshot BOARD --output FILE\n";
}

bool same_file(
    const std::filesystem::path& first,
    const std::filesystem::path& second
) {
    std::error_code error;
    const bool equivalent = std::filesystem::equivalent(
        first,
        second,
        error
    );

    if (!error && equivalent) {
        return true;
    }

    error.clear();
    const std::filesystem::path first_absolute =
        std::filesystem::absolute(first, error);

    if (error) {
        return false;
    }

    const std::filesystem::path second_absolute =
        std::filesystem::absolute(second, error);
    return
        !error &&
        first_absolute.lexically_normal() ==
            second_absolute.lexically_normal();
}

} // namespace

int main(int argc, char** argv) {
    const bool snapshot =
        argc == 5 &&
        std::string_view{argv[1]} == "snapshot" &&
        std::string_view{argv[3]} == "--output" &&
        !std::string_view{argv[2]}.empty() &&
        !std::string_view{argv[4]}.empty();

    if (!snapshot) {
        usage();
        return EXIT_FAILURE;
    }

    const std::string board_path = argv[2];
    const std::string output_path = argv[4];

    if (same_file(board_path, output_path)) {
        std::cerr <<
            "whiteboard-inspect: output must differ from the board file\n";
        return EXIT_FAILURE;
    }

    Board board;
    CardSpatial spatial;
    GlyphLayer glyphs;
    const CardFormats formats = make_card_formats();

    std::string error;
    if (!whiteboard::io::load_project(
            board_path,
            board,
            spatial,
            glyphs,
            formats,
            &error
        )) {
        std::cerr << "whiteboard-inspect: cannot load "
                  << board_path << ": " << error << '\n';
        return EXIT_FAILURE;
    }

    AtomicFileWriter writer(output_path);

    if (!writer.good()) {
        std::cerr << "whiteboard-inspect: cannot create output: "
                  << writer.error() << '\n';
        return EXIT_FAILURE;
    }

    if (!whiteboard::verification::write_canonical_snapshot(
            writer.stream(),
            board,
            spatial,
            glyphs,
            formats
        )) {
        std::cerr << "whiteboard-inspect: snapshot serialization failed\n";
        return EXIT_FAILURE;
    }

    if (!writer.commit()) {
        std::cerr << "whiteboard-inspect: cannot commit output: "
                  << writer.error() << '\n';
        return EXIT_FAILURE;
    }

    return EXIT_SUCCESS;
}
