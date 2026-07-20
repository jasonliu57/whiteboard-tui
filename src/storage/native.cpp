#include "native.hpp"
#include "atomic_file.hpp"
#include "limits.hpp"
#include <fstream>
#include <new>

namespace whiteboard::io {

namespace {
void describe_native_exception(std::string* error, const char* message) noexcept {
    if (error != nullptr) {
        try {
            *error = message;
        } catch (...) {
            // Reporting an I/O failure must not throw on allocation failure.
        }
    }
}
} // namespace

bool save_project(
    const std::string& path,
    const Board& board,
    const GlyphLayer& glyphs,
    std::string* error
) try {
    if (error != nullptr) error->clear();
    AtomicFileWriter writer(path);
    if (!writer.good() ||
        !encode_project(writer.stream(), board, glyphs, error) ||
        !writer.commit()) {
        if (error != nullptr) {
            *error = writer.published()
                ? "file published; durability not confirmed: "
                : "save failed: ";
            error->append(writer.error().empty() ? "serialization failed" : writer.error());
        }
        return false;
    }
    return true;
} catch (const std::bad_alloc&) {
    describe_native_exception(error, "not enough memory for project I/O");
    return false;
} catch (...) {
    describe_native_exception(error, "project I/O failed");
    return false;
}

bool load_project(
    const std::string& path,
    Board& board,
    CardSpatial& spatial,
    GlyphLayer& glyphs,
    const CardFormats& formats,
    std::string* error
) try {
    if (error != nullptr) *error = "cannot read project";
    std::ifstream file(path, std::ios::binary | std::ios::ate);
    if (!file) return false;
    const std::streampos end = file.tellg();
    if (end < 0 || static_cast<u64>(end) > kMaximumProjectBytes) return false;
    file.seekg(0, std::ios::beg);
    if (!file) return false;
    return decode_project(file, static_cast<u64>(end), board,
                          spatial, glyphs, formats, error);
} catch (const std::bad_alloc&) {
    describe_native_exception(error, "not enough memory for project I/O");
    return false;
} catch (...) {
    describe_native_exception(error, "project I/O failed");
    return false;
}

} // namespace whiteboard::io
