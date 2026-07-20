#include "standalone_fixture.hpp"
#include "../src/platform/native/app_io.hpp"

#include <iostream>

int main(int argc, char** argv) {
    if (argc != 2 && argc != 3) return 2;
    App app{80, 24};
    if (argc == 3 && std::string_view(argv[2]) == "overview-extreme") {
        const i64 maximum = std::numeric_limits<i64>::max();
        const i64 minimum = std::numeric_limits<i64>::min();
        if (app.add_card(make_plain_text_note({maximum - 200, minimum + 200}, 20, 8)) == kNoCard ||
            !app.glyphs.insert({maximum - 220, minimum + 180}, U'中')) return 1;
    } else if (argc == 2) populate_standalone_fixture(app);
    else return 2;
    if (!whiteboard::native::save(app, argv[1])) {
        std::cerr << app.file_error << '\n';
        return 1;
    }
}
