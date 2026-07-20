#include "../src/platform/native/app_io.hpp"
#include "../src/app.hpp"
#include "../src/generated/protocol_limits.hpp"
#include "../src/storage/project.hpp"

#include <absl/container/inlined_vector.h>

#include <array>
#include <chrono>
#include <clocale>
#include <cstddef>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <memory>
#include <streambuf>
#include <sstream>
#include <string>
#include <string_view>
#include <utility>
#include <vector>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

#ifndef WHITEBOARD_BUILD_TYPE
#define WHITEBOARD_BUILD_TYPE "unknown"
#endif
#ifndef WHITEBOARD_COMPILER_ID
#define WHITEBOARD_COMPILER_ID "unknown"
#endif
#ifndef WHITEBOARD_COMPILER_VERSION
#define WHITEBOARD_COMPILER_VERSION "unknown"
#endif
#ifndef WHITEBOARD_SYSTEM_NAME
#define WHITEBOARD_SYSTEM_NAME "unknown"
#endif
#ifndef WHITEBOARD_SYSTEM_PROCESSOR
#define WHITEBOARD_SYSTEM_PROCESSOR "unknown"
#endif

struct StressConfig {
    u32 columns = 1000;
    u32 rows = 100;
    u32 point_iterations = 100000;
    u32 viewport_iterations = 10000;
    u32 render_iterations = 1000;
    u32 format_iterations = 1000;
    u32 syntax_iterations = 500;
    u32 layout_iterations = 100;
    u32 bulk_iterations = 200;
    u32 route_iterations = 100;
    u32 syntax_begin_iterations = 10;
    std::string scenario = "board";
    bool quick = false;

    u32 card_count() const {
        return columns * rows;
    }

    u32 edge_count() const {
        return
            rows * (columns - 1) +
            (rows - 1) * columns;
    }

    Rect world() const {
        constexpr i64 stride = 37;
        constexpr i64 card_size = 32;
        return {
            0,
            0,
            static_cast<i64>(columns - 1) * stride + card_size,
            static_cast<i64>(rows - 1) * stride + card_size,
        };
    }
};

static StressConfig quick_config() {
    return {
        .columns = 100,
        .rows = 10,
        .point_iterations = 2000,
        .viewport_iterations = 200,
        .render_iterations = 40,
        .format_iterations = 40,
        .syntax_iterations = 30,
        .layout_iterations = 20,
        .bulk_iterations = 10,
        .route_iterations = 5,
        .syntax_begin_iterations = 2,
        .quick = true,
    };
}

static u64 peak_rss_kib() {
    rusage usage{};

    if (::getrusage(RUSAGE_SELF, &usage) != 0) {
        return 0;
    }

#if defined(__APPLE__)
    return static_cast<u64>(usage.ru_maxrss) / 1024;
#else
    return static_cast<u64>(usage.ru_maxrss);
#endif
}

struct BenchmarkResult {
    std::string name;
    u64 iterations = 0;
    u64 input_objects = 0;
    u64 input_bytes = 0;
    u64 output_bytes = 0;
    double milliseconds = 0.0;
    u64 observed = 0;
    u64 output_checksum = 0;
    u64 peak_kib = 0;
};

struct BenchmarkObservation {
    u64 observed = 0;
    u64 output_bytes = 0;
    u64 checksum = 0;
};

struct Benchmark {
    std::vector<BenchmarkResult> results;
    u64 checksum = 0xcbf29ce484222325ULL;

    Benchmark() {
        results.reserve(128);
    }

    void mix(u64 value) {
        checksum ^= value + 0x9e3779b97f4a7c15ULL +
            (checksum << 6) + (checksum >> 2);
    }

    template<class Action>
    bool measure_io(
        std::string name,
        u64 iterations,
        u64 input_objects,
        u64 input_bytes,
        Action&& action
    ) {
        BenchmarkObservation observation;
        const auto begin = std::chrono::steady_clock::now();
        const bool ok = action(observation);
        const auto end = std::chrono::steady_clock::now();
        const double milliseconds =
            std::chrono::duration<double, std::milli>(end - begin).count();

        if (observation.checksum == 0) {
            observation.checksum = observation.observed;
        }

        results.push_back({
            .name = std::move(name),
            .iterations = iterations,
            .input_objects = input_objects,
            .input_bytes = input_bytes,
            .output_bytes = observation.output_bytes,
            .milliseconds = milliseconds,
            .observed = observation.observed,
            .output_checksum = observation.checksum,
            .peak_kib = peak_rss_kib(),
        });
        mix(observation.observed);
        mix(observation.output_bytes);
        mix(observation.checksum);
        mix(iterations);
        return ok;
    }

    template<class Action>
    bool measure(
        std::string name,
        u64 iterations,
        Action&& action
    ) {
        return measure_io(
            std::move(name),
            iterations,
            iterations,
            0,
            [&](BenchmarkObservation& observation) {
                return action(observation.observed);
            }
        );
    }

    void print(const StressConfig& config, u64 file_size) const {
        std::cout
            << "benchmark_schema,2\n"
            << "scenario," << config.scenario << '\n'
            << "mode," << (config.quick ? "quick" : "full") << '\n'
            << "compiler," << WHITEBOARD_COMPILER_ID << '\n'
            << "compiler_version," << WHITEBOARD_COMPILER_VERSION << '\n'
            << "build_type," << WHITEBOARD_BUILD_TYPE << '\n'
            << "os," << WHITEBOARD_SYSTEM_NAME << '\n'
            << "architecture," << WHITEBOARD_SYSTEM_PROCESSOR << '\n'
            << "cards," << config.card_count() << '\n'
            << "edges," << config.edge_count() << '\n'
            << "board_file_bytes," << file_size << '\n'
            << "checksum," << checksum << '\n'
            << "name,iterations,input_objects,input_bytes,output_bytes,"
               "total_ms,ns_per_item,mib_per_second,observed,"
               "output_checksum,peak_rss_mib\n";

        std::cout << std::fixed << std::setprecision(3);

        for (const BenchmarkResult& result : results) {
            const double nanoseconds = result.iterations == 0
                ? 0.0
                : result.milliseconds * 1'000'000.0 /
                    static_cast<double>(result.iterations);
            const u64 throughput_bytes = std::max(
                result.input_bytes,
                result.output_bytes
            );
            const double mib_per_second =
                result.milliseconds == 0.0
                    ? 0.0
                    : static_cast<double>(throughput_bytes) /
                        (1024.0 * 1024.0) /
                        (result.milliseconds / 1000.0);

            std::cout
                << result.name << ','
                << result.iterations << ','
                << result.input_objects << ','
                << result.input_bytes << ','
                << result.output_bytes << ','
                << result.milliseconds << ','
                << nanoseconds << ','
                << mib_per_second << ','
                << result.observed << ','
                << result.output_checksum << ','
                << static_cast<double>(result.peak_kib) / 1024.0
                << '\n';
        }
    }
};

static bool require_condition(
    bool condition,
    std::string_view message
) {
    if (condition) {
        return true;
    }

    std::cerr << "stress benchmark failed: " << message << '\n';
    return false;
}

struct TemporaryBoardFile {
    std::string path;

    TemporaryBoardFile() {
        path = "/tmp/whiteboard-stress-";
        append_decimal(path, ::getpid());
        path.append(".tiwb");
    }

    ~TemporaryBoardFile() {
        ::unlink(path.c_str());
    }
};

static Pos card_position(const StressConfig& config, CardId id) {
    constexpr i64 stride = 37;
    return {
        static_cast<i64>(id % config.columns) * stride,
        static_cast<i64>(id / config.columns) * stride,
    };
}

static Card make_stress_card(CardId id, Pos position) {
    Card card;

    switch (id) {
        case 0: {
            card = make_plain_text_note(position, 32, 32);
            TextCardData& data = std::get<TextCardData>(card.data);
            data.lines = {
                "Stress note",
                "UTF-8: \xE4\xB8\xAD\xE6\x96\x87",
            };
            break;
        }

        case 1: {
            card = make_markdown_card(position, 32, 32);
            TextCardData& data = std::get<TextCardData>(card.data);
            data.lines = {
                "# Stress benchmark",
                "",
                "- **bold** and `code`",
                "- [link](https://example.com)",
                "UTF-8 \xE4\xB8\xAD\xE6\x96\x87",
            };
            break;
        }

        case 2: {
            card = make_code_card(position, kCppLanguageId, 32, 32);
            TextCardData& data = std::get<TextCardData>(card.data);
            data.lines = {
                "#include <vector>",
                "int main() {",
                "    std::vector<int> values{1, 2, 3};",
                "    return values.size();",
                "}",
            };
            break;
        }

        case 3: {
            card = make_todo_card(position, 32, 32);
            TodoCardData& data = std::get<TodoCardData>(card.data);
            data.items = {
                {"first task", false},
                {"finished task", true},
            };
            break;
        }

        case 4: {
            card = make_csv_card(position, 32, 32);
            CsvCardData& data = std::get<CsvCardData>(card.data);
            data.cells = {
                {"alpha", "beta", "gamma"},
                {"1", "\xE4\xB8\xAD", "3"},
            };
            data.column_widths = {12, 12, 12};
            data.styled_cells = {
                {0, 1, Style{3, 0, AttrBold}},
            };
            break;
        }

        case 5: {
            card = make_folder_card(position, 32, 32);
            FolderCardData& data = std::get<FolderCardData>(card.data);
            data.name = "stress";
            data.entries = {
                {
                    .kind = FolderEntryKind::Directory,
                    .depth = 0,
                    .name = "src",
                    .target = kNoCard,
                    .collapsed = false,
                },
                {
                    .kind = FolderEntryKind::Card,
                    .depth = 1,
                    .name = "README.md",
                    .target = 1,
                },
                {
                    .kind = FolderEntryKind::Card,
                    .depth = 1,
                    .name = "main.cpp",
                    .target = 2,
                },
                {
                    .kind = FolderEntryKind::Card,
                    .depth = 0,
                    .name = "note.txt",
                    .target = 0,
                },
            };
            break;
        }

        default:
            card = make_plain_text_note(position, 32, 32);
            break;
    }

    return card;
}

static bool build_cards(App& app, const StressConfig& config) {
    const u32 count = config.card_count();
    app.board.cards.reserve(count);
    app.board.incident.reserve(count);

    for (CardId id = 0; id < count; ++id) {
        Card card = make_stress_card(id, card_position(config, id));

        if (id < 6) {
            app.formats[card.static_format].rebuild(card.data);
        }

        const CardId inserted = app.board.add(std::move(card));

        if (inserted != id) {
            return false;
        }
    }

    return true;
}

static bool build_card_grid(
    App& app,
    const StressConfig& config
) {
    const u32 card_count = config.card_count();
    app.spatial.reset_slots(card_count);
    app.spatial.reserve(card_count, card_count * 2ULL);

    for (CardId id = 0; id < card_count; ++id) {
        app.spatial.change(
            id,
            rect_at(card_position(config, id), {32, 32})
        );
    }

    return app.spatial.validate();
}

static Edge make_direct_edge(
    const App& app,
    EdgeEnd source,
    EdgeEnd target
) {
    Edge edge;
    edge.source = source;
    edge.target = target;
    edge.mode = RouteMode::Manual;
    edge.state = RouteState::Ready;
    edge.points = {
        app.port_geometry(source).position,
        app.port_geometry(target).position,
    };
    edge.route_bounds = edge_segment_rect(
        edge.points.front(),
        edge.points.back()
    );
    return edge;
}

static bool build_edges(App& app, const StressConfig& config) {
    const u32 expected = config.edge_count();
    app.board.edges.reserve(expected);

    for (u32 row = 0; row < config.rows; ++row) {
        for (u32 column = 0; column + 1 < config.columns; ++column) {
            const CardId source = row * config.columns + column;
            const EdgeId id = app.board.add_edge(make_direct_edge(
                app,
                {source, PortSide::Right},
                {source + 1, PortSide::Left}
            ));

            if (id + 1 != app.board.edges.size()) {
                return false;
            }
        }
    }

    for (u32 row = 0; row + 1 < config.rows; ++row) {
        for (u32 column = 0; column < config.columns; ++column) {
            const CardId source = row * config.columns + column;
            const EdgeId id = app.board.add_edge(make_direct_edge(
                app,
                {source, PortSide::Bottom},
                {source + config.columns, PortSide::Top}
            ));

            if (id + 1 != app.board.edges.size()) {
                return false;
            }
        }
    }

    return app.board.edges.size() == expected;
}

static bool validate_fixture(
    const App& app,
    const StressConfig& config
) {
    const u32 cards = config.card_count();
    const u32 edges = config.edge_count();
    const auto fail = [](const char* reason) {
        std::cerr << "fixture invariant failed: " << reason << '\n';
        return false;
    };

    if (
        app.board.cards.size() != cards ||
        app.board.incident.size() != cards ||
        app.board.live_cards != cards ||
        app.spatial.slots.size() != cards ||
        app.spatial.live_count() != cards ||
        app.board.edges.size() != edges ||
        app.board.live_edges != edges ||
        app.edge_spatial.slot_count != edges ||
        !app.spatial.validate()
    ) {
        std::cerr
            << "cards=" << app.board.cards.size()
            << " incident=" << app.board.incident.size()
            << " live_cards=" << app.board.live_cards
            << " spatial_slots=" << app.spatial.slots.size()
            << " edge_slots=" << app.board.edges.size()
            << " live_edges=" << app.board.live_edges
            << " edge_index_slots=" << app.edge_spatial.slot_count
            << " grid_cells=" << app.spatial.occupied_cell_count()
            << " grid_entries=" << app.spatial.bucket_entry_count()
            << '\n';
        return fail("top-level sizes");
    }

    if (
        app.spatial.occupied_cell_count() == 0 ||
        app.spatial.bucket_entry_count() < cards
    ) {
        return fail("card grid sizes");
    }

    for (CardId id = 0; id < cards; ++id) {
        const Card* card = app.board.find(id);
        const CardSpatialSlot& slot = app.spatial.slots[id];

        if (
            card == nullptr ||
            !slot.alive ||
            slot.rect != rect_at(card_position(config, id), {32, 32})
        ) {
            return fail("card slot");
        }
    }

    std::vector<u8> seen(cards, 0);
    u64 card_visits = 0;

    if (!app.spatial.query(config.world(), [&](CardId id) {
            if (id >= cards || seen[id] != 0) {
                return false;
            }

            seen[id] = 1;
            ++card_visits;
            return true;
    })) {
        return fail("card query traversal");
    }

    u64 incident = 0;

    for (const auto& list : app.board.incident) {
        incident += list.size();
    }

    if (card_visits != cards || incident != static_cast<u64>(edges) * 2) {
        return fail("card visits or adjacency");
    }

    u64 edge_visits = 0;

    if (!app.edge_spatial.query(
            config.world(),
            [&](const EdgeSegmentRef&) {
                ++edge_visits;
                return true;
            }
        )) {
        return fail("edge query traversal");
    }

    if (edge_visits != edges) {
        return fail("edge segment visits");
    }

    for (EdgeId id = 0; id < edges; ++id) {
        const Edge* edge = app.board.find_edge(id);

        if (
            edge == nullptr ||
            edge->points.size() != 2
        ) {
            return fail("edge slot");
        }
    }

    return true;
}

static u64 next_random(u64& state) {
    state = state * 6364136223846793005ULL +
        1442695040888963407ULL;
    return state;
}

static Viewport random_viewport(
    const StressConfig& config,
    u64& state
) {
    constexpr i32 width = 160;
    constexpr i32 height = 48;
    const Rect world = config.world();
    const u64 horizontal = static_cast<u64>(world.right + width);
    const u64 vertical = static_cast<u64>(world.bottom + height);
    const i64 x = static_cast<i64>(next_random(state) % horizontal) -
        width / 2;
    const i64 y = static_cast<i64>(next_random(state) % vertical) -
        height / 2;
    return {x, y, width, height};
}

static void warm_up(App& app) {
    app.spatial.query(point_rect({1, 1}), [](CardId) {
        return true;
    });
    app.edge_spatial.query(
        {0, 0, 160, 48},
        [](const EdgeSegmentRef&) {
            return true;
        }
    );

    const Viewport viewport{0, 0, 160, 48};
    app.render(viewport, viewport_rect(viewport));
    app.screen.clear();
}

static bool benchmark_validation(
    Benchmark& benchmark,
    const App& app,
    const StressConfig& config
) {
    return benchmark.measure(
        "validate.all_edges",
        config.edge_count(),
        [&](u64& observed) {
            for (EdgeId id = 0; id < config.edge_count(); ++id) {
                if (!validate_edge(
                        app.board,
                        app.spatial,
                        app.board.get_edge(id)
                    )) {
                    return false;
                }

                ++observed;
            }

            return true;
        }
    );
}

static bool benchmark_card_queries(
    Benchmark& benchmark,
    const App& app,
    const StressConfig& config
) {
    u64 random = 0x123456789abcdef0ULL;

    if (!benchmark.measure(
            "query.card_point_hit",
            config.point_iterations,
            [&](u64& observed) {
                for (u32 i = 0; i < config.point_iterations; ++i) {
                    const CardId expected = static_cast<CardId>(
                        next_random(random) % config.card_count()
                    );
                    const Pos position = card_position(config, expected);
                    const CardId found = app.card_at({
                        position.x + 1,
                        position.y + 1,
                    });

                    if (found != expected) {
                        return false;
                    }

                    observed += static_cast<u64>(found) + 1;
                }

                return true;
            }
        )) {
        return false;
    }

    if (!benchmark.measure(
            "query.card_point_miss",
            config.point_iterations,
            [&](u64& observed) {
                for (u32 i = 0; i < config.point_iterations; ++i) {
                    const u32 column = static_cast<u32>(
                        next_random(random) % config.columns
                    );
                    const u32 row = static_cast<u32>(
                        next_random(random) % config.rows
                    );
                    const CardId id = row * config.columns + column;
                    const Pos position = card_position(config, id);
                    const CardId found = app.card_at({
                        position.x + 34,
                        position.y + 34,
                    });

                    if (found != kNoCard) {
                        return false;
                    }

                    ++observed;
                }

                return true;
            }
        )) {
        return false;
    }

    if (!benchmark.measure(
            "query.card_early_stop",
            config.point_iterations,
            [&](u64& observed) {
                for (u32 i = 0; i < config.point_iterations; ++i) {
                    u32 visits = 0;
                    const bool completed = app.spatial.query(
                        config.world(),
                        [&](CardId id) {
                            observed += static_cast<u64>(id) + 1;
                            ++visits;
                            return false;
                        }
                    );

                    if (completed || visits != 1) {
                        return false;
                    }
                }

                return true;
            }
        )) {
        return false;
    }

    if (!benchmark.measure(
            "query.card_viewport",
            config.viewport_iterations,
            [&](u64& observed) {
                for (u32 i = 0; i < config.viewport_iterations; ++i) {
                    const Viewport viewport = random_viewport(
                        config,
                        random
                    );

                    if (!app.spatial.query(
                            viewport_rect(viewport),
                            [&](CardId id) {
                                observed += static_cast<u64>(id) + 1;
                                return true;
                            }
                        )) {
                        return false;
                    }
                }

                return true;
            }
        )) {
        return false;
    }

    return benchmark.measure(
        "query.card_full",
        1,
        [&](u64& observed) {
            u64 visits = 0;
            const bool completed = app.spatial.query(
                config.world(),
                [&](CardId id) {
                    ++visits;
                    observed += static_cast<u64>(id) + 1;
                    return true;
                }
            );
            return completed && visits == config.card_count();
        }
    );
}

static bool benchmark_edge_queries(
    Benchmark& benchmark,
    const App& app,
    const StressConfig& config
) {
    u64 random = 0x0f1e2d3c4b5a6978ULL;

    if (!benchmark.measure(
            "query.edge_viewport",
            config.viewport_iterations,
            [&](u64& observed) {
                for (u32 i = 0; i < config.viewport_iterations; ++i) {
                    const Viewport viewport = random_viewport(
                        config,
                        random
                    );

                    if (!app.edge_spatial.query(
                            viewport_rect(viewport),
                            [&](const EdgeSegmentRef& segment) {
                                observed +=
                                    static_cast<u64>(segment.edge) + 1;
                                return true;
                            }
                        )) {
                        return false;
                    }
                }

                return true;
            }
        )) {
        return false;
    }

    return benchmark.measure(
        "query.edge_full",
        1,
        [&](u64& observed) {
            u64 visits = 0;
            const bool completed = app.edge_spatial.query(
                config.world(),
                [&](const EdgeSegmentRef& segment) {
                    ++visits;
                    observed += static_cast<u64>(segment.edge) + 1;
                    return true;
                }
            );
            return completed && visits == config.edge_count();
        }
    );
}

static bool benchmark_render(
    Benchmark& benchmark,
    App& app,
    const StressConfig& config
) {
    u64 random = 0x3141592653589793ULL;

    if (!benchmark.measure(
            "render.viewport",
            config.render_iterations,
            [&](u64& observed) {
                for (u32 i = 0; i < config.render_iterations; ++i) {
                    const Viewport viewport = random_viewport(
                        config,
                        random
                    );
                    const Pos cursor{
                        viewport.x + viewport.width / 2,
                        viewport.y + viewport.height / 2,
                    };
                    const CardId hovered = app.card_at(cursor);
                    const CardId selected = i % 3 == 0
                        ? hovered
                        : kNoCard;
                    app.render(
                        viewport,
                        viewport_rect(viewport),
                        hovered,
                        selected
                    );

                    const ScreenCell& first = app.screen.at(0, 0);
                    const ScreenCell& middle = app.screen.at(
                        app.screen.width() / 2,
                        app.screen.height() / 2
                    );
                    observed += static_cast<u64>(first.glyph);
                    observed += static_cast<u64>(middle.glyph);
                    observed += first.owner == kNoCard
                        ? 0
                        : static_cast<u64>(first.owner) + 1;
                }

                return true;
            }
        )) {
        return false;
    }

    app.begin_card(1);
    random = 0x2718281828459045ULL;
    const bool active_ok = benchmark.measure(
        "render.active_markdown",
        config.render_iterations,
        [&](u64& observed) {
            for (u32 i = 0; i < config.render_iterations; ++i) {
                const Viewport viewport = i == 0
                    ? Viewport{0, 0, 160, 48}
                    : random_viewport(config, random);
                app.render(
                    viewport,
                    viewport_rect(viewport),
                    kNoCard,
                    1
                );
                const ScreenCell& cell = app.screen.at(
                    app.screen.width() / 2,
                    app.screen.height() / 2
                );
                observed += static_cast<u64>(cell.glyph);
            }

            return true;
        }
    );
    app.end_card();
    return active_ok;
}

static void reset_history(App& app) {
    app.history.clear();
    app.untracked_dirty = false;
}

template<class Apply>
static bool benchmark_history_sequence(
    Benchmark& benchmark,
    App& app,
    std::string name,
    u32 count,
    Apply&& apply
) {
    reset_history(app);

    if (!benchmark.measure(
            name + ".apply",
            count,
            [&](u64& observed) {
                for (u32 i = 0; i < count; ++i) {
                    const std::size_t before = app.history.cursor;

                    if (!apply(i) || app.history.cursor != before + 1) {
                        return false;
                    }

                    ++observed;
                }

                return true;
            }
        )) {
        return false;
    }

    if (!benchmark.measure(
            name + ".undo",
            count,
            [&](u64& observed) {
                for (u32 i = 0; i < count; ++i) {
                    if (!app.undo()) {
                        return false;
                    }

                    ++observed;
                }

                return true;
            }
        )) {
        return false;
    }

    if (!benchmark.measure(
            name + ".redo",
            count,
            [&](u64& observed) {
                for (u32 i = 0; i < count; ++i) {
                    if (!app.redo()) {
                        return false;
                    }

                    ++observed;
                }

                return true;
            }
        )) {
        return false;
    }

    for (u32 i = 0; i < count; ++i) {
        if (!app.undo()) {
            return false;
        }
    }

    reset_history(app);
    return true;
}

static bool apply_stored_input(App& app, const InputEvent& event) {
    const std::size_t before = app.history.cursor;
    const u64 revision = app.revision;
    const AppInputResult result = app.handle_active_input(event);
    return
        result.handled &&
        app.history.cursor == before + 1 &&
        app.revision == revision + 1;
}

template<class Prepare, class Step>
static bool benchmark_format_sequence(
    Benchmark& benchmark,
    App& app,
    std::string name,
    CardId card,
    u32 count,
    Prepare&& prepare,
    Step&& step
) {
    app.begin_card(card);
    prepare();
    const CardData before = app.board.get(card).data;
    const bool ok = benchmark_history_sequence(
        benchmark,
        app,
        std::move(name),
        count,
        [&](u32 i) {
            return step(i);
        }
    );
    const bool restored = app.board.get(card).data == before;
    app.end_card();
    return ok && restored;
}

static bool benchmark_syntax_begin(
    Benchmark& benchmark,
    App& app,
    const StressConfig& config
) {
    if (!benchmark.measure(
            "format.markdown_begin",
            config.syntax_begin_iterations,
            [&](u64& observed) {
                for (u32 i = 0;
                     i < config.syntax_begin_iterations;
                     ++i) {
                    app.begin_card(1);
                    observed += text_style_span_count(
                        std::get<TextCardData>(
                            app.board.get(1).data
                        ).styles
                    );
                    app.end_card();
                }

                return true;
            }
        )) {
        return false;
    }

    return benchmark.measure(
        "format.cpp_begin",
        config.syntax_begin_iterations,
        [&](u64& observed) {
            for (u32 i = 0;
                 i < config.syntax_begin_iterations;
                 ++i) {
                app.begin_card(2);
                observed += text_style_span_count(
                    std::get<TextCardData>(
                        app.board.get(2).data
                    ).styles
                );
                app.end_card();
            }

            return true;
        }
    );
}

static InputEvent key_event(
    Key key,
    bool shift = false,
    bool ctrl = false
) {
    return {
        .key = key,
        .text = {},
        .shift = shift,
        .ctrl = ctrl,
    };
}

static bool benchmark_formats(
    Benchmark& benchmark,
    App& app,
    const StressConfig& config
) {
    const InputEvent text_x{.key = Key::Text, .text = "x"};
    const InputEvent text_utf8{
        .key = Key::Text,
        .text = "\xE4\xB8\xAD",
    };
    const InputEvent code_text{
        .key = Key::Text,
        .text = " int value = 1;",
    };
    const InputEvent enter = key_event(Key::Enter);
    const InputEvent tab = key_event(Key::Tab);
    const InputEvent delete_key = key_event(Key::Delete);
    const InputEvent ctrl_a = key_event(Key::CtrlA);
    const InputEvent ctrl_b = key_event(Key::CtrlB);
    const InputEvent ctrl_x = key_event(Key::CtrlX);
    const InputEvent page_up = key_event(Key::PageUp);
    const InputEvent layout_right = key_event(
        Key::Right,
        false,
        true
    );
    const InputEvent layout_left = key_event(
        Key::Left,
        false,
        true
    );

    if (!benchmark_format_sequence(
            benchmark,
            app,
            "format.note_text",
            0,
            config.format_iterations,
            [] {},
            [&](u32) {
                return apply_stored_input(app, text_x);
            }
        )) {
        return false;
    }

    if (!benchmark_format_sequence(
            benchmark,
            app,
            "format.note_layout",
            0,
            config.layout_iterations,
            [] {},
            [&](u32 i) {
                return apply_stored_input(
                    app,
                    i % 2 == 0 ? layout_right : layout_left
                );
            }
        )) {
        return false;
    }

    if (!benchmark_format_sequence(
            benchmark,
            app,
            "format.note_style",
            0,
            1,
            [&] {
                app.handle_active_input(ctrl_a);
            },
            [&](u32) {
                return apply_stored_input(app, ctrl_b);
            }
        )) {
        return false;
    }

    if (!benchmark_format_sequence(
            benchmark,
            app,
            "format.markdown_incremental",
            1,
            config.syntax_iterations,
            [] {},
            [&](u32 i) {
                return apply_stored_input(
                    app,
                    i % 10 == 0 ? enter : text_utf8
                );
            }
        )) {
        return false;
    }

    if (!benchmark_format_sequence(
            benchmark,
            app,
            "format.cpp_incremental",
            2,
            config.syntax_iterations,
            [] {},
            [&](u32 i) {
                return apply_stored_input(
                    app,
                    i % 8 == 0 ? enter : code_text
                );
            }
        )) {
        return false;
    }

    if (!benchmark_format_sequence(
            benchmark,
            app,
            "format.todo_toggle",
            3,
            config.format_iterations,
            [] {},
            [&](u32) {
                return apply_stored_input(app, tab);
            }
        )) {
        return false;
    }

    if (!benchmark_format_sequence(
            benchmark,
            app,
            "format.todo_text",
            3,
            config.format_iterations,
            [] {},
            [&](u32) {
                return apply_stored_input(app, text_x);
            }
        )) {
        return false;
    }

    if (!benchmark_format_sequence(
            benchmark,
            app,
            "format.todo_insert",
            3,
            config.bulk_iterations,
            [] {},
            [&](u32) {
                return apply_stored_input(app, enter);
            }
        )) {
        return false;
    }

    if (!benchmark_format_sequence(
            benchmark,
            app,
            "format.todo_delete",
            3,
            2,
            [] {},
            [&](u32) {
                return apply_stored_input(app, delete_key);
            }
        )) {
        return false;
    }

    if (!benchmark_format_sequence(
            benchmark,
            app,
            "format.todo_style",
            3,
            config.format_iterations,
            [] {},
            [&](u32) {
                return apply_stored_input(app, ctrl_b);
            }
        )) {
        return false;
    }

    if (!benchmark_format_sequence(
            benchmark,
            app,
            "format.todo_layout",
            3,
            config.layout_iterations,
            [] {},
            [&](u32 i) {
                return apply_stored_input(
                    app,
                    i % 2 == 0 ? layout_right : layout_left
                );
            }
        )) {
        return false;
    }

    if (!benchmark_format_sequence(
            benchmark,
            app,
            "format.csv_text",
            4,
            config.format_iterations,
            [] {},
            [&](u32) {
                return apply_stored_input(app, text_x);
            }
        )) {
        return false;
    }

    if (!benchmark_format_sequence(
            benchmark,
            app,
            "format.csv_style",
            4,
            config.format_iterations,
            [] {},
            [&](u32) {
                return apply_stored_input(app, ctrl_b);
            }
        )) {
        return false;
    }

    if (!benchmark_format_sequence(
            benchmark,
            app,
            "format.csv_insert_row",
            4,
            config.bulk_iterations,
            [&] {
                CsvSession& session =
                    std::get<CsvSession>(app.session.state);
                const CsvCardData& data = std::get<CsvCardData>(
                    app.board.get(4).data
                );
                session.row = static_cast<u32>(data.cells.size() - 1);
            },
            [&](u32) {
                return apply_stored_input(app, enter);
            }
        )) {
        return false;
    }

    if (!benchmark_format_sequence(
            benchmark,
            app,
            "format.csv_delete_row",
            4,
            2,
            [] {},
            [&](u32) {
                return apply_stored_input(app, ctrl_x);
            }
        )) {
        return false;
    }

    if (!benchmark_format_sequence(
            benchmark,
            app,
            "format.csv_widths",
            4,
            1,
            [] {},
            [&](u32) {
                return apply_stored_input(app, page_up);
            }
        )) {
        return false;
    }

    if (!benchmark_format_sequence(
            benchmark,
            app,
            "format.csv_layout",
            4,
            config.layout_iterations,
            [] {},
            [&](u32 i) {
                return apply_stored_input(
                    app,
                    i % 2 == 0 ? layout_right : layout_left
                );
            }
        )) {
        return false;
    }

    if (!benchmark_format_sequence(
            benchmark,
            app,
            "format.folder_rename",
            5,
            config.format_iterations,
            [] {},
            [&](u32) {
                return apply_stored_input(app, text_x);
            }
        )) {
        return false;
    }

    if (!benchmark_format_sequence(
            benchmark,
            app,
            "format.folder_collapse",
            5,
            config.format_iterations,
            [&] {
                std::get<FolderSession>(
                    app.session.state
                ).selected_entry = 0;
            },
            [&](u32) {
                return apply_stored_input(app, enter);
            }
        )) {
        return false;
    }

    if (!benchmark_format_sequence(
            benchmark,
            app,
            "format.folder_insert",
            5,
            config.bulk_iterations,
            [] {},
            [&](u32) {
                return apply_stored_input(app, ctrl_a);
            }
        )) {
        return false;
    }

    if (!benchmark_format_sequence(
            benchmark,
            app,
            "format.folder_delete_subtree",
            5,
            1,
            [&] {
                std::get<FolderSession>(
                    app.session.state
                ).selected_entry = 0;
            },
            [&](u32) {
                return apply_stored_input(app, delete_key);
            }
        )) {
        return false;
    }

    if (!benchmark_format_sequence(
            benchmark,
            app,
            "format.folder_indent_delta",
            5,
            1,
            [&] {
                std::get<FolderSession>(
                    app.session.state
                ).selected_entry = 3;
            },
            [&](u32) {
                return apply_stored_input(app, tab);
            }
        )) {
        return false;
    }

    const InputEvent shift_tab = key_event(Key::Tab, true);

    if (!benchmark_format_sequence(
            benchmark,
            app,
            "format.folder_outdent_delta",
            5,
            1,
            [&] {
                std::get<FolderSession>(
                    app.session.state
                ).selected_entry = 1;
            },
            [&](u32) {
                return apply_stored_input(app, shift_tab);
            }
        )) {
        return false;
    }

    return benchmark_format_sequence(
        benchmark,
        app,
        "format.folder_layout",
        5,
        config.layout_iterations,
        [] {},
        [&](u32 i) {
            return apply_stored_input(
                app,
                i % 2 == 0 ? layout_right : layout_left
            );
        }
    );
}

static bool benchmark_spatial_updates(
    Benchmark& benchmark,
    App& app,
    const StressConfig& config
) {
    const CardId id =
        (config.rows / 2) * config.columns + config.columns / 2;
    const Rect original = app.spatial.slots[id].rect;
    const Rect shifted{
        original.left + kCardSpatialCellWidth,
        original.top + kCardSpatialCellHeight,
        original.right + kCardSpatialCellWidth,
        original.bottom + kCardSpatialCellHeight,
    };

    if (!benchmark.measure(
            "spatial.card_change",
            config.format_iterations,
            [&](u64& observed) {
                for (u32 i = 0; i < config.format_iterations; ++i) {
                    app.spatial.change(
                        id,
                        i % 2 == 0 ? shifted : original
                    );
                    observed += static_cast<u64>(
                        app.spatial.slots[id].rect.left
                    ) + 1;
                }
                return true;
            }
        )) {
        return false;
    }

    bool found = false;
    const Pos probe{original.left + 1, original.top + 1};

    return
        app.spatial.slots[id].rect == original &&
        app.spatial.validate() &&
        app.spatial.query(point_rect(probe), [&](CardId candidate) {
            found = found || candidate == id;
            return true;
        }) &&
        found;
}

static bool glyph_equals(
    const App& app,
    Pos pos,
    char32_t glyph
) {
    const auto cell = app.glyphs.cells.find(pos);
    return
        cell != app.glyphs.cells.end() &&
        cell->second == glyph;
}

static bool benchmark_persistence(
    Benchmark& benchmark,
    std::unique_ptr<App>& app,
    const StressConfig& config,
    const std::string& path,
    u64& file_size
) {
    if (
        !app->set_glyph({-9, -9}, 'A') ||
        !app->set_glyph({-8, -9}, 'B') ||
        !app->set_glyph({-9, -8}, 'C') ||
        !app->set_glyph({-7, -8}, 'D') ||
        !app->set_glyph({-5, -8}, U'中')
    ) {
        return false;
    }

    if (!benchmark.measure(
            "storage.save_project",
            1,
            [&](u64& observed) {
                const bool saved = whiteboard::native::save(*app, path);
                if (!saved) {
                    std::cerr << "stress persistence: save failed\n";
                }
                observed = saved
                    ? static_cast<u64>(app->board.cards.size()) +
                        app->board.edges.size() +
                        app->glyphs.cells.size()
                    : 0;
                return saved;
            }
        )) {
        return false;
    }

    struct stat information{};

    if (::stat(path.c_str(), &information) != 0) {
        return false;
    }

    file_size = static_cast<u64>(information.st_size);
    app.reset();
    std::unique_ptr<App> loaded = std::make_unique<App>(160, 48);

    if (!benchmark.measure(
            "storage.load_project",
            1,
            [&](u64& observed) {
                const bool loaded_ok = whiteboard::native::load(*loaded, path);
                if (!loaded_ok) {
                    std::cerr << "stress persistence: load failed\n";
                }
                observed = loaded_ok
                    ? static_cast<u64>(loaded->board.cards.size()) +
                        loaded->board.edges.size() +
                        loaded->glyphs.cells.size()
                    : 0;
                return loaded_ok;
            }
        )) {
        return false;
    }

    if (
        !validate_fixture(*loaded, config) ||
        loaded->glyphs.cells.size() != 5 ||
        !glyph_equals(*loaded, {-9, -9}, 'A') ||
        !glyph_equals(*loaded, {-8, -9}, 'B') ||
        !glyph_equals(*loaded, {-9, -8}, 'C') ||
        !glyph_equals(*loaded, {-7, -8}, 'D') ||
        !glyph_equals(*loaded, {-5, -8}, U'中')
    ) {
        std::cerr << "stress persistence: round-trip mismatch\n";
        return false;
    }

    app = std::move(loaded);
    return true;
}

static bool benchmark_glyph_operations(
    Benchmark& benchmark,
    App& app,
    const StressConfig& config
) {
    const Viewport viewport{-12, -12, 160, 48};

    if (!benchmark.measure(
            "glyph.render",
            config.render_iterations,
            [&](u64& observed) {
                for (u32 i = 0; i < config.render_iterations; ++i) {
                    app.render(viewport, viewport_rect(viewport));
                    observed += app.screen.at(3, 3).glyph;
                }

                return
                    app.screen.at(3, 3).glyph == U'A' &&
                    app.screen.at(7, 4).glyph == U'中' &&
                    app.screen.at(7, 4).width == 2 &&
                    app.screen.at(8, 4).width == 0;
            }
        )) {
        return false;
    }

    reset_history(app);
    const std::size_t history_before = app.history.cursor;

    if (
        !app.move_glyphs({-9, -9, -8, -8}, {1, 0}) ||
        !glyph_equals(app, {-8, -9}, U'A') ||
        app.glyphs.cells.contains({-9, -9}) ||
        !app.set_glyph({-9, -9}, U'A') ||
        !app.set_glyph({-8, -9}, U'B') ||
        app.history.cursor != history_before
    ) {
        return false;
    }

    if (
        !app.move_glyphs({-5, -8, -3, -7}, {-2, 0}) ||
        !glyph_equals(app, {-7, -8}, U'中') ||
        app.glyphs.cells.contains({-5, -8}) ||
        !app.set_glyph({-7, -8}, U'D') ||
        !app.set_glyph({-5, -8}, U'中') ||
        app.history.cursor != history_before
    ) {
        return false;
    }

    if (
        !app.set_glyph({-20, -20}, U'X') ||
        !app.set_glyph({-19, -20}, U'Y') ||
        !app.set_glyph({-20, -20}, U'中') ||
        !glyph_equals(app, {-20, -20}, U'中') ||
        app.glyphs.cells.contains({-19, -20}) ||
        app.glyphs.anchor_at({-19, -20}) == app.glyphs.cells.end() ||
        !app.set_glyph({-19, -20}, U' ') ||
        app.glyphs.cells.contains({-20, -20}) ||
        app.history.cursor != history_before ||
        !app.untracked_dirty
    ) {
        return false;
    }

    if (
        !app.move_glyphs({-4, -8, -3, -7}, {0, 1}) ||
        !glyph_equals(app, {-5, -7}, U'中') ||
        !app.move_glyphs({-4, -7, -3, -6}, {0, -1}) ||
        !glyph_equals(app, {-5, -8}, U'中') ||
        app.history.cursor != history_before
    ) {
        return false;
    }

    if (
        !app.set_glyph({-20, -20}, U'中') ||
        !app.set_glyph({-17, -20}, U'Z') ||
        !app.erase_glyphs({-19, -20, -16, -19}) ||
        app.glyphs.cells.contains({-20, -20}) ||
        app.glyphs.cells.contains({-17, -20}) ||
        app.history.cursor != history_before
    ) {
        return false;
    }

    if (!benchmark.measure(
            "glyph.set",
            config.bulk_iterations,
            [&](u64& observed) {
                for (u32 i = 0; i < config.bulk_iterations; ++i) {
                    if (!app.set_glyph(
                            {
                                -100 - static_cast<i64>(i),
                                -100,
                            },
                            static_cast<char>('a' + i % 26)
                        )) {
                        return false;
                    }

                    ++observed;
                }

                return app.history.cursor == history_before;
            }
        )) {
        return false;
    }

    if (!app.erase_glyphs({
            -99 - static_cast<i64>(config.bulk_iterations),
            -100,
            -99,
            -99,
        })) {
        return false;
    }

    if (!benchmark.measure(
            "glyph.move",
            config.format_iterations,
            [&](u64& observed) {
                for (u32 i = 0; i < config.format_iterations; ++i) {
                    const bool moved = i % 2 == 0
                        ? app.move_glyphs(
                            {-4, -8, -3, -7},
                            {0, 1}
                        )
                        : app.move_glyphs(
                            {-4, -7, -3, -6},
                            {0, -1}
                        );

                    if (!moved) {
                        return false;
                    }

                    ++observed;
                }

                return app.history.cursor == history_before;
            }
        )) {
        return false;
    }

    return
        app.glyphs.cells.size() == 5 &&
        glyph_equals(app, {-9, -9}, 'A') &&
        glyph_equals(app, {-8, -9}, 'B') &&
        glyph_equals(app, {-9, -8}, 'C') &&
        glyph_equals(app, {-7, -8}, 'D') &&
        glyph_equals(app, {-5, -8}, U'中');
}

static CardId center_card(const StressConfig& config) {
    return
        (config.rows / 2) * config.columns +
        config.columns / 2;
}

static Rect edge_points_bounds(const EdgePoints& points) {
    Rect bounds = edge_segment_rect(points[0], points[1]);

    for (u32 i = 1; i + 1 < points.size(); ++i) {
        bounds = unite(
            bounds,
            edge_segment_rect(points[i], points[i + 1])
        );
    }

    return bounds;
}

static Edge make_dogleg_edge(
    const App& app,
    CardId source
) {
    Edge edge = make_direct_edge(
        app,
        {source, PortSide::Right},
        {source + 1, PortSide::Left}
    );
    const Pos first = edge.points.front();
    const Pos last = edge.points.back();
    edge.points = {
        first,
        {first.x + 1, first.y},
        {first.x + 1, first.y + 1},
        {last.x - 1, last.y + 1},
        {last.x - 1, last.y},
        last,
    };
    edge.route_bounds = edge_points_bounds(edge.points);
    return edge;
}

static Edge make_generated_manual_edge(
    const App& app,
    CardId source
) {
    Edge edge;
    edge.source = {source, PortSide::Right};
    edge.target = {source + 1, PortSide::Left};
    edge.mode = RouteMode::Manual;
    edge.state = RouteState::Ready;
    const PortGeometry source_port = app.port_geometry(edge.source);
    const PortGeometry target_port = app.port_geometry(edge.target);
    make_manual_edge_leg(
        {source_port.position, source_port.direction, true},
        {target_port.position, target_port.direction, true},
        true,
        edge.points
    );
    edge.route_bounds = edge_points_bounds(edge.points);
    return edge;
}

static bool benchmark_edge_operations(
    Benchmark& benchmark,
    App& app,
    const StressConfig& config
) {
    const CardId source = center_card(config);
    const CardId target = source + 1;
    const Rect first_rect = app.spatial.slots[source].rect;
    const Rect second_rect = app.spatial.slots[target].rect;
    const Rect joined = unite(first_rect, second_rect);
    const Rect route_bounds{
        joined.left - 2,
        joined.top - 2,
        joined.right + 2,
        joined.bottom + 2,
    };

    if (!benchmark.measure(
            "edge.automatic_route",
            config.route_iterations,
            [&](u64& observed) {
                for (u32 i = 0; i < config.route_iterations; ++i) {
                    Edge edge;
                    edge.source = {source, PortSide::Right};
                    edge.target = {target, PortSide::Left};

                    if (!app.route_edge(edge, route_bounds)) {
                        return false;
                    }

                    observed += edge.points.size();
                }

                return true;
            }
        )) {
        return false;
    }

    if (!benchmark.measure(
            "edge.manual_prepare",
            config.route_iterations,
            [&](u64& observed) {
                for (u32 i = 0; i < config.route_iterations; ++i) {
                    Edge edge = make_generated_manual_edge(app, source);

                    if (!app.prepare_manual_edge(edge)) {
                        return false;
                    }

                    observed += edge.points.size();
                }

                return true;
            }
        )) {
        return false;
    }

    const u32 count = std::min<u32>(
        config.bulk_iterations,
        config.columns - 1
    );
    std::vector<Edge> replacements;
    replacements.reserve(count);

    for (u32 i = 0; i < count; ++i) {
        Edge edge = make_dogleg_edge(app, i);

        if (!app.prepare_manual_edge(edge)) {
            return false;
        }

        replacements.push_back(std::move(edge));
    }

    if (!benchmark_history_sequence(
            benchmark,
            app,
            "edge.replace",
            count,
            [&](u32 i) {
                app.replace_edge(i, std::move(replacements[i]));
                return true;
            }
        )) {
        return false;
    }

    if (!benchmark_history_sequence(
            benchmark,
            app,
            "edge.delete",
            count,
            [&](u32 i) {
                app.erase_edge(i);
                return true;
            }
        )) {
        return false;
    }

    const CardId obstacle = source + 2 * config.columns;
    const Pos obstacle_destination{
        first_rect.right,
        first_rect.top,
    };
    const EdgeId blocked_edge =
        (source / config.columns) * (config.columns - 1) +
        source % config.columns;

    if (!benchmark_history_sequence(
            benchmark,
            app,
            "edge.obstacle_block",
            1,
            [&](u32) {
                return
                    app.move_card(obstacle, obstacle_destination) &&
                    app.board.get_edge(blocked_edge).state ==
                        RouteState::Blocked;
            }
        )) {
        return false;
    }

    if (app.board.get_edge(blocked_edge).state != RouteState::Ready) {
        return false;
    }

    return benchmark_history_sequence(
        benchmark,
        app,
        "edge.add",
        count,
        [&](u32) {
            app.add_edge(make_direct_edge(
                app,
                {source, PortSide::Right},
                {target, PortSide::Left}
            ));
            return true;
        }
    );
}

static bool benchmark_card_operations(
    Benchmark& benchmark,
    App& app,
    const StressConfig& config
) {
    const CardId moved = center_card(config);
    const Pos original = app.board.get(moved).pos;
    const Pos shifted{original.x + 1, original.y};

    if (!benchmark_history_sequence(
            benchmark,
            app,
            "card.move",
            config.format_iterations,
            [&](u32 i) {
                return app.move_card(
                    moved,
                    i % 2 == 0 ? shifted : original
                );
            }
        )) {
        return false;
    }

    if (app.board.get(moved).pos != original) {
        return false;
    }

    const u32 delete_count = std::min<u32>(
        config.bulk_iterations,
        config.card_count() - config.columns - 10
    );
    const CardId delete_first = config.columns + 10;

    if (!benchmark_history_sequence(
            benchmark,
            app,
            "card.delete",
            delete_count,
            [&](u32 i) {
                app.erase_card(delete_first + i);
                return true;
            }
        )) {
        return false;
    }

    if (!benchmark.measure(
            "card.copy",
            config.format_iterations,
            [&](u64& observed) {
                for (u32 i = 0; i < config.format_iterations; ++i) {
                    app.copy_card(1);
                    const CardClipboard* copy =
                        std::get_if<CardClipboard>(&app.clipboard);

                    if (copy == nullptr || copy->source != 1) {
                        return false;
                    }

                    observed += copy->name.size() + 1;
                }

                return true;
            }
        )) {
        return false;
    }

    const Rect world = config.world();
    const u32 add_count = config.bulk_iterations;

    if (!benchmark_history_sequence(
            benchmark,
            app,
            "card.add",
            add_count,
            [&](u32 i) {
                const Pos position{
                    world.right + 100 + static_cast<i64>(i) * 37,
                    0,
                };
                return app.add_card(
                    make_plain_text_note(position, 32, 32)
                ) != kNoCard;
            }
        )) {
        return false;
    }

    app.copy_card(1);

    if (!benchmark_history_sequence(
            benchmark,
            app,
            "card.paste",
            add_count,
            [&](u32 i) {
                const Pos position{
                    static_cast<i64>(i) * 37,
                    world.bottom + 100,
                };
                return app.paste_card(position) != kNoCard;
            }
        )) {
        return false;
    }

    return app.board.live_cards == config.card_count();
}

static bool final_live_validation(
    const App& app,
    const StressConfig& config
) {
    u64 cards = 0;

    if (!app.spatial.query(config.world(), [&](CardId id) {
            if (app.board.find(id) == nullptr) {
                return false;
            }

            ++cards;
            return true;
        })) {
        return false;
    }

    u64 edges = 0;

    for (const std::optional<Edge>& edge : app.board.edges) {
        edges += edge.has_value();
    }

    return
        cards == config.card_count() &&
        app.board.live_cards == config.card_count() &&
        edges == config.edge_count() &&
        app.board.live_edges == edges &&
        app.glyphs.cells.size() == 5;
}

static bool validate_todo_replacement_metadata() {
    TodoCardData data;
    data.items.clear();
    TodoItem first{"stale one", false};
    first.style = {4, 1, AttrBold};
    data.items.push_back(std::move(first));
    TodoItem second{"stale two", true};
    second.style = {6, 2, AttrUnderline};
    data.items.push_back(std::move(second));
    CardData card_data = std::move(data);

    const bool decoded = whiteboard::io::read_card_content(
        "- [x] refreshed one\n"
        "- [ ] refreshed two\n"
        "- [x] new item",
        SaveFormat::TodoText,
        card_data
    );
    const TodoCardData& result = std::get<TodoCardData>(card_data);

    return
        decoded &&
        result.items.size() == 3 &&
        result.items[0].text == "refreshed one" &&
        result.items[0].done &&
        result.items[0].style == Style{4, 1, AttrBold} &&
        result.items[1].text == "refreshed two" &&
        !result.items[1].done &&
        result.items[1].style == Style{6, 2, AttrUnderline} &&
        result.items[2].text == "new item" &&
        result.items[2].done &&
        result.items[2].style == Style{2, 0, AttrNone};
}

class DigestOutputBuffer final : public std::streambuf {
public:
    void reset() noexcept {
        bytes_ = 0;
        checksum_ = 0xFFFFFFFFU;
    }

    u64 bytes() const noexcept {
        return bytes_;
    }

    u64 checksum() const noexcept {
        return checksum_ ^ 0xFFFFFFFFU;
    }

protected:
    std::streamsize xsputn(
        const char* data,
        std::streamsize size
    ) override {
        if (size > 0) {
            account(data, static_cast<std::size_t>(size));
        }
        return size;
    }

    int_type overflow(int_type character) override {
        if (!traits_type::eq_int_type(character, traits_type::eof())) {
            const char byte = traits_type::to_char_type(character);
            account(&byte, 1);
        }
        return traits_type::not_eof(character);
    }

private:
    u64 bytes_ = 0;
    u32 checksum_ = 0xFFFFFFFFU;

    void account(const char* data, std::size_t size) noexcept {
        bytes_ += size;
        checksum_ = update_project_crc32(checksum_, data, size);
    }
};

static bool measure_native(
    Benchmark& benchmark,
    std::string name,
    u64 input_objects,
    u64 input_bytes,
    const Board& board,
    const GlyphLayer& glyphs
) {
    DigestOutputBuffer buffer;
    std::ostream output(&buffer);
    return benchmark.measure_io(
        std::move(name),
        input_objects,
        input_objects,
        input_bytes,
        [&](BenchmarkObservation& observation) {
            const bool written =
                write_main_file_content(output, board, glyphs);
            observation.observed = written ? input_objects : 0;
            observation.output_bytes = buffer.bytes();
            observation.checksum = buffer.checksum();
            return written;
        }
    );
}

static bool run_registry_create_benchmark(const StressConfig& config) {
    const u32 count = config.quick ? 1'000 : 100'000;
    const CardFormats formats = make_card_formats();
    std::vector<Card> cards;
    cards.reserve(count);
    Benchmark benchmark;

    if (!benchmark.measure_io(
            "registry.create_mixed",
            count,
            count,
            0,
            [&](BenchmarkObservation& observation) {
                u64 checksum = 0;

                for (CardId index = 0; index < count; ++index) {
                    const StaticFormatId id = index % formats.size();
                    Card card;

                    if (!create_registered_card(
                            formats,
                            id,
                            {static_cast<i64>(index) * 2, 0},
                            formats[id].minimum_layout,
                            card
                        )) {
                        return false;
                    }

                    checksum = checksum * 131 + card.static_format + 1;
                    cards.push_back(std::move(card));
                }

                observation.observed = cards.size();
                observation.checksum = checksum;
                return cards.size() == count;
            }
        )) {
        return false;
    }

    benchmark.print(config, 0);
    return true;
}

static std::string make_card_batch(
    const CardFormats& formats,
    std::size_t limit,
    bool invalid_tail
) {
    constexpr std::string_view invalid = "unknown 0 0 1 1\n";
    const std::size_t content_limit = invalid_tail
        ? limit - invalid.size()
        : limit;
    std::string batch;
    batch.reserve(limit);

    for (u32 index = 0;; ++index) {
        const StaticFormatId id = index % formats.size();
        const CardFormat& format = formats[id];
        std::string line{format.name};
        line.push_back(' ');
        append_decimal(line, static_cast<i64>(index) * 2);
        line.append(" 0 ");
        append_decimal(line, format.minimum_layout.width);
        line.push_back(' ');
        append_decimal(line, format.minimum_layout.height);
        line.push_back('\n');

        if (line.size() > content_limit - batch.size()) {
            break;
        }

        batch.append(line);
    }

    if (invalid_tail) {
        batch.append(invalid);
    }

    return batch;
}

static bool run_create_cards_benchmark(const StressConfig& config) {
    const CardFormats formats = make_card_formats();
    const std::size_t limit = config.quick ? 32 * 1024 : kAgentTextLimit;
    const std::string batch = make_card_batch(formats, limit, false);
    std::vector<Card> cards;
    u32 invalid_line = 0;
    Benchmark benchmark;

    if (!benchmark.measure_io(
            "create_cards.parse_construct",
            1,
            1,
            batch.size(),
            [&](BenchmarkObservation& observation) {
                const RegisteredCardBatchResult result =
                    build_registered_card_batch(
                        formats,
                        batch,
                        cards,
                        invalid_line
                    );
                observation.observed = cards.size();
                observation.output_bytes = cards.size() * sizeof(Card);
                observation.checksum = cards.size();
                return
                    result == RegisteredCardBatchResult::Success &&
                    invalid_line == 0 &&
                    !cards.empty();
            }
        )) {
        return false;
    }

    const u64 card_count = cards.size();
    App app(160, 48);

    if (!benchmark.measure_io(
            "create_cards.commit",
            card_count,
            card_count,
            batch.size(),
            [&](BenchmarkObservation& observation) {
                const CardId first = app.add_cards(std::move(cards));
                observation.observed = app.board.live_cards;
                observation.checksum = app.revision;
                return first == 0 && app.board.live_cards == card_count;
            }
        ) ||
        !benchmark.measure(
            "create_cards.undo",
            card_count,
            [&](u64& observed) {
                const bool undone = app.undo();
                observed = app.board.live_cards;
                return undone && observed == 0;
            }
        ) ||
        !benchmark.measure(
            "create_cards.redo",
            card_count,
            [&](u64& observed) {
                const bool redone = app.redo();
                observed = app.board.live_cards;
                return redone && observed == card_count;
            }
        )) {
        return false;
    }

    const std::string rejected = make_card_batch(formats, limit, true);
    std::vector<Card> untouched;
    Card sentinel;
    sentinel.static_format = kTextArtStaticFormatId;
    untouched.push_back(std::move(sentinel));
    App rejected_app(160, 48);

    if (!benchmark.measure_io(
            "create_cards.reject_tail",
            1,
            1,
            rejected.size(),
            [&](BenchmarkObservation& observation) {
                u32 line = 0;
                const RegisteredCardBatchResult result =
                    build_registered_card_batch(
                        formats,
                        rejected,
                        untouched,
                        line
                    );
                observation.observed = line;
                observation.checksum = line;
                return
                    result == RegisteredCardBatchResult::InvalidLine &&
                    line != 0 &&
                    untouched.size() == 1 &&
                    untouched[0].static_format == kTextArtStaticFormatId &&
                    rejected_app.board.cards.empty() &&
                    rejected_app.history.entries.empty() &&
                    rejected_app.revision == 0;
            }
        )) {
        return false;
    }

    benchmark.print(config, 0);
    return true;
}

static bool build_dense_native_fixture(
    App& app,
    const StressConfig& config
) {
    return
        build_cards(app, config) &&
        build_card_grid(app, config) &&
        build_edges(app, config);
}

static bool run_native_dense_benchmark(const StressConfig& config) {
    App app(160, 48);

    if (!build_dense_native_fixture(app, config)) {
        return false;
    }

    Benchmark benchmark;
    const u64 objects =
        app.board.live_cards + app.board.live_edges;

    if (!measure_native(
            benchmark,
            "native.dense_board",
            objects,
            0,
            app.board,
            app.glyphs
        )) {
        return false;
    }

    benchmark.print(config, 0);
    return true;
}

static bool run_native_payload_benchmark(const StressConfig& config) {
    const std::size_t bytes = config.quick
        ? 1024 * 1024
        : 64 * 1024 * 1024;
    App app(160, 48);
    Card card = make_plain_text_note({0, 0});
    std::get<TextCardData>(card.data).lines = {std::string(bytes, 'x')};

    if (app.add_card(std::move(card)) == kNoCard) {
        return false;
    }

    Benchmark benchmark;

    if (!measure_native(
            benchmark,
            "native.payload_heavy",
            1,
            bytes,
            app.board,
            app.glyphs
        )) {
        return false;
    }

    benchmark.print(config, 0);
    return true;
}

static bool run_native_glyph_benchmark(const StressConfig& config) {
    const u32 count = config.quick ? 10'000 : 1'000'000;
    Board board;
    GlyphLayer glyphs;
    glyphs.cells.reserve(count);

    for (u32 index = 0; index < count; ++index) {
        const Pos position{
            static_cast<i64>(index % 10'000) * 2,
            static_cast<i64>(index / 10'000),
        };

        if (!glyphs.insert(position, U'A')) {
            return false;
        }
    }

    Benchmark benchmark;

    if (!measure_native(
            benchmark,
            "native.glyph_heavy",
            count,
            static_cast<u64>(count) * sizeof(GlyphCell),
            board,
            glyphs
        )) {
        return false;
    }

    benchmark.print(config, 0);
    return true;
}

static bool run_native_tombstone_benchmark(const StressConfig& config) {
    const u32 slot_count = config.quick ? 10'000 : 1'000'000;
    constexpr u32 stride = 10;
    Board board;
    const CardFormats formats = make_card_formats();
    board.cards.resize(slot_count);
    board.incident.resize(slot_count);

    for (CardId id = 0; id < slot_count; id += stride) {
        Card card;
        const Pos position{
            static_cast<i64>(id % 1'000) * 20,
            static_cast<i64>(id / 1'000) * 10,
        };

        if (!create_registered_card(
                formats,
                kPlainTextNoteStaticFormatId,
                position,
                formats[kPlainTextNoteStaticFormatId].minimum_layout,
                card
            )) {
            return false;
        }

        board.cards[id].emplace(std::move(card));
        ++board.live_cards;
    }

    Benchmark benchmark;

    if (!measure_native(
            benchmark,
            "native.tombstones",
            slot_count,
            0,
            board,
            GlyphLayer{}
        )) {
        return false;
    }

    benchmark.print(config, 0);
    return true;
}

static bool run_native_repeatability_benchmark(
    const StressConfig& config
) {
    const u32 count = config.quick ? 10'000 : 100'000;
    Board board;
    GlyphLayer glyphs;
    glyphs.cells.reserve(count);

    for (u32 index = 0; index < count; ++index) {
        if (!glyphs.insert(
                {
                    static_cast<i64>((count - index) % 10'000) * 2,
                    static_cast<i64>((count - index) / 10'000),
                },
                U'A'
            )) {
            return false;
        }
    }

    DigestOutputBuffer buffer;
    std::ostream output(&buffer);
    Benchmark benchmark;

    if (!benchmark.measure_io(
            "native.repeatability",
            3,
            count,
            static_cast<u64>(count) * sizeof(GlyphCell),
            [&](BenchmarkObservation& observation) {
                u64 expected_bytes = 0;
                u64 expected_checksum = 0;
                u64 total_bytes = 0;

                for (u32 iteration = 0; iteration < 3; ++iteration) {
                    buffer.reset();
                    output.clear();

                    if (!write_main_file_content(output, board, glyphs)) {
                        return false;
                    }

                    if (iteration == 0) {
                        expected_bytes = buffer.bytes();
                        expected_checksum = buffer.checksum();
                    } else if (
                        buffer.bytes() != expected_bytes ||
                        buffer.checksum() != expected_checksum
                    ) {
                        return false;
                    }

                    total_bytes += buffer.bytes();
                }

                observation.observed = 3;
                observation.output_bytes = total_bytes;
                observation.checksum = expected_checksum;
                return true;
            }
        )) {
        return false;
    }

    benchmark.print(config, 0);
    return true;
}

static bool run_stress_benchmark(const StressConfig& config) {
    if (
        config.card_count() < 1000 ||
        config.card_count() % 10 != 0 ||
        config.format_iterations % 2 != 0 ||
        config.layout_iterations % 2 != 0
    ) {
        return require_condition(false, "invalid fixed configuration");
    }

    if (!require_condition(
            validate_todo_replacement_metadata(),
            "todo replacement metadata"
        )) {
        return false;
    }

    Benchmark benchmark;
    std::unique_ptr<App> app = std::make_unique<App>(160, 48);

    if (!require_condition(
            benchmark.measure(
                "fixture.cards",
                config.card_count(),
                [&](u64& observed) {
                    const bool built = build_cards(*app, config);
                    observed = built ? app->board.cards.size() : 0;
                    return built;
                }
            ),
            "card fixture"
        )) {
        return false;
    }

    if (!require_condition(
            benchmark.measure(
                "fixture.card_grid",
                config.card_count(),
                [&](u64& observed) {
                    const bool built = build_card_grid(*app, config);
                    observed = built
                        ? app->spatial.occupied_cell_count()
                        : 0;
                    return built;
                }
            ),
            "card grid fixture"
        )) {
        return false;
    }

    if (!require_condition(
            benchmark.measure(
                "fixture.edges",
                config.edge_count(),
                [&](u64& observed) {
                    const bool built = build_edges(*app, config);
                    observed = built ? app->board.edges.size() : 0;
                    return built;
                }
            ),
            "edge fixture"
        )) {
        return false;
    }

    if (!require_condition(
            benchmark.measure(
                "fixture.edge_index",
                config.edge_count(),
                [&](u64& observed) {
                    app->edge_spatial.rebuild(app->board);
                    observed = app->edge_spatial.slot_count;
                    return observed == config.edge_count();
                }
            ),
            "edge spatial fixture"
        )) {
        return false;
    }

    reset_history(*app);

    if (!require_condition(
            validate_fixture(*app, config),
            "initial fixture invariants"
        )) {
        return false;
    }

    warm_up(*app);

    if (!require_condition(
            benchmark_validation(benchmark, *app, config),
            "edge validation benchmark"
        ) ||
        !require_condition(
            benchmark_card_queries(benchmark, *app, config),
            "card query benchmark"
        ) ||
        !require_condition(
            benchmark_edge_queries(benchmark, *app, config),
            "edge query benchmark"
        ) ||
        !require_condition(
            benchmark_render(benchmark, *app, config),
            "render benchmark"
        ) ||
        !require_condition(
            benchmark_syntax_begin(benchmark, *app, config),
            "syntax begin benchmark"
        )) {
        return false;
    }

    TemporaryBoardFile file;
    u64 file_size = 0;

    if (!require_condition(
            benchmark_persistence(
                benchmark,
                app,
                config,
                file.path,
                file_size
            ),
            "persistence benchmark"
        )) {
        return false;
    }

    benchmark.mix(file_size);

    if (!require_condition(
            benchmark_spatial_updates(benchmark, *app, config),
            "card spatial update benchmark"
        ) ||
        !require_condition(
            benchmark_formats(benchmark, *app, config),
            "format benchmark"
        ) ||
        !require_condition(
            benchmark_glyph_operations(benchmark, *app, config),
            "glyph benchmark"
        ) ||
        !require_condition(
            benchmark_edge_operations(benchmark, *app, config),
            "edge mutation benchmark"
        ) ||
        !require_condition(
            benchmark_card_operations(benchmark, *app, config),
            "card mutation benchmark"
        ) ||
        !require_condition(
            final_live_validation(*app, config),
            "final live-state invariants"
        )) {
        return false;
    }

    benchmark.mix(app->revision);
    benchmark.print(config, file_size);
    return true;
}

struct StressScenario {
    std::string_view name;
    bool (*run)(const StressConfig&);
};

constexpr StressScenario kStressScenarios[]{
#define WHITEBOARD_STRESS_SCENARIO(name, function) {name, function},
#include "../benchmarks/stress_scenarios.def"
#undef WHITEBOARD_STRESS_SCENARIO
};

static bool run_named_benchmark(const StressConfig& config) {
    const auto found = std::find_if(
        std::begin(kStressScenarios),
        std::end(kStressScenarios),
        [&config](const StressScenario& scenario) {
            return scenario.name == config.scenario;
        }
    );
    return found != std::end(kStressScenarios) && found->run(config);
}

static int run_all_benchmark_processes(
    const char* executable,
    bool quick
) {
    for (const StressScenario& scenario : kStressScenarios) {
        std::cout << "# process " << scenario.name << '\n' << std::flush;
        const pid_t child = ::fork();

        if (child < 0) {
            return 1;
        }

        if (child == 0) {
            if (quick) {
                ::execlp(
                    executable,
                    executable,
                    "--quick",
                    "--scenario",
                    scenario.name.data(),
                    static_cast<char*>(nullptr)
                );
            } else {
                ::execlp(
                    executable,
                    executable,
                    "--scenario",
                    scenario.name.data(),
                    static_cast<char*>(nullptr)
                );
            }

            ::_exit(127);
        }

        int status = 0;

        if (
            ::waitpid(child, &status, 0) != child ||
            !WIFEXITED(status) ||
            WEXITSTATUS(status) != 0
        ) {
            return 1;
        }
    }

    return 0;
}

static void stress_usage() {
    std::cout
        << "usage: whiteboard_stress [--quick] [--scenario NAME]\n"
        << "default scenario: board (100000 cards, 198900 edges)\n"
        << "scenarios: all";
    for (const StressScenario& scenario : kStressScenarios) {
        std::cout << ", " << scenario.name;
    }
    std::cout << "\n--quick: reduced correctness workload\n";
}

int main(int argc, char** argv) {
    ::setlocale(LC_CTYPE, "");
    bool quick = false;
    std::string scenario = "board";

    for (int argument = 1; argument < argc; ++argument) {
        const std::string_view value{argv[argument]};

        if (value == "--quick") {
            quick = true;
        } else if (value == "--scenario" && argument + 1 < argc) {
            scenario = argv[++argument];
        } else if (value == "--help" || value == "-h") {
            stress_usage();
            return 0;
        } else {
            stress_usage();
            return 2;
        }
    }

    if (scenario == "all") {
        return run_all_benchmark_processes(argv[0], quick);
    }

    StressConfig config = quick ? quick_config() : StressConfig{};
    config.scenario = scenario;

    if (run_named_benchmark(config)) {
        return 0;
    }

    std::cerr << "unknown or failed stress scenario: " << scenario << '\n';
    return 1;
}
