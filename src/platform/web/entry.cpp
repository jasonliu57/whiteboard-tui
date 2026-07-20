#include "../../tui/all.hpp"
#include "../../tui/presenter.hpp"
#include "../../render/overview.hpp"
#include "../../storage/string_view_stream.hpp"

#include <emscripten/emscripten.h>
#include <memory>
#include <sstream>
#include <stdexcept>

namespace {
constexpr std::size_t kMaximumFileBytes = 32U * 1024U * 1024U;
constexpr u64 kDecodeBudget = 128ULL * 1024ULL * 1024ULL;
constexpr std::size_t kMaximumInputBytes = 1024U * 1024U;

struct WebSession {
    Tui tui;
    InputDecoder decoder;
    TerminalPresenter presenter;
    bool save_requested = false;
    BoardProjection overview_projection;
    std::vector<float> overview_geometry;
    u64 overview_revision = 0;
    bool overview_valid = false;

    WebSession(i32 width, i32 height)
        : tui(width, height, "", TuiHost{
            .context = this,
            .command = [](void* context, TuiAction action) {
                auto& session = *static_cast<WebSession*>(context);
                if (action == TuiAction::Save) {
                    session.save_requested = true;
                    return true;
                }
                if (action == TuiAction::QuitClean || action == TuiAction::ForceQuit) {
                    session.tui.set_message("Use the page controls to open or close a document");
                    return true;
                }
                return false;
            },
        }) {}
};

std::unique_ptr<WebSession> session;
std::string result;
std::string error;

void dimensions(i32 width, i32 height) {
    if (width < 2 || height < 2 || width > 500 || height > 250 ||
        static_cast<i64>(width) * height > 50000)
        throw std::runtime_error("viewport exceeds the browser cell budget");
}

void build_overview(WebSession& current) {
    const auto& app = current.tui.app();
    if (current.overview_valid && current.overview_revision == app.revision) return;
    current.overview_valid = false;
    auto& geometry = current.overview_geometry;
    geometry.clear();
    auto& projection = current.overview_projection;
    const bool found = board_overview_bounds(app.board, app.spatial, projection.bounds, &app.glyphs);
    // Internal wire format: Float32 [version, aspect, (kind, color, x1,y1,x2,y2)*].
    // At most 65,536 primitives (1.5 MiB); never publish a partial overview.
    geometry.push_back(1);
    geometry.push_back(found ? static_cast<float>(
        BoardProjection::distance(projection.bounds.right, projection.bounds.left) /
        BoardProjection::distance(projection.bounds.bottom, projection.bounds.top)) : 0);
    const auto add = [&](float kind, float color, Pos first, Pos second) {
        if (geometry.size() >= 2 + 6 * 65'536) {
            geometry.clear();
            throw std::runtime_error("內容過多，小地圖暫不可用");
        }
        geometry.insert(geometry.end(), {kind, color,
            static_cast<float>(projection.x(first.x)), static_cast<float>(projection.y(first.y)),
            static_cast<float>(projection.x(second.x)), static_cast<float>(projection.y(second.y))});
    };
    for (EdgeId id = 0; id < app.board.edges.size(); ++id) {
        const Edge* edge = app.board.find_edge(id);
        if (!edge || !app.board.find(edge->source.card) || !app.board.find(edge->target.card)) continue;
        for (std::size_t i = 1; i < edge->points.size(); ++i)
            add(2, edge->state == RouteState::Ready ? 0 : 1, edge->points[i - 1], edge->points[i]);
    }
    for (const auto& [pos, glyph] : app.glyphs.cells) {
        const Rect rect = glyph_bounds(pos, glyph);
        add(1, 0, {rect.left, rect.top}, {rect.right, rect.bottom});
    }
    for (CardId id = 0; id < app.board.cards.size(); ++id) {
        if (const Card* card = app.board.find(id)) {
            const Rect rect = app.spatial.slots[id].rect;
            add(0, card->static_format % 8, {rect.left, rect.top}, {rect.right, rect.bottom});
        }
    }
    current.overview_revision = app.revision;
    current.overview_valid = true;
}

template<class F> int operation(F&& action) noexcept {
    try {
        error.clear();
        if (!session) throw std::runtime_error("whiteboard is not initialized");
        action();
        return 1;
    } catch (const std::exception& failure) {
        error = failure.what();
    } catch (...) {
        error = "whiteboard operation failed";
    }
    return 0;
}
} // namespace

extern "C" {
EMSCRIPTEN_KEEPALIVE int wb_create(int width, int height) {
    try {
        dimensions(width, height);
        auto replacement = std::make_unique<WebSession>(width, height);
        session = std::move(replacement);
        error.clear();
        return 1;
    } catch (const std::exception& failure) {
        error = failure.what();
        return 0;
    }
}

EMSCRIPTEN_KEEPALIVE void wb_destroy() {
    session.reset();
    std::string{}.swap(result);
}

EMSCRIPTEN_KEEPALIVE const char* wb_error() { return error.c_str(); }
EMSCRIPTEN_KEEPALIVE const char* wb_result() { return result.data(); }
EMSCRIPTEN_KEEPALIVE std::size_t wb_result_size() { return result.size(); }

EMSCRIPTEN_KEEPALIVE int wb_input(const char* bytes, std::size_t size, int flush) {
    return operation([&] {
        if (size > kMaximumInputBytes ||
            session->decoder.pending_size() > kMaximumInputBytes - size) {
            session->decoder = InputDecoder{};
            throw std::runtime_error("pending input exceeds 1 MiB");
        }
        if (size) session->decoder.append({bytes, size});
        InputEvent event;
        while (session->decoder.next(event, flush != 0)) session->tui.handle(event);
    });
}

EMSCRIPTEN_KEEPALIVE std::size_t wb_pending_input() {
    return session ? session->decoder.pending_size() : 0;
}

EMSCRIPTEN_KEEPALIVE int wb_resize(int width, int height) {
    return operation([&] {
        dimensions(width, height);
        session->tui.resize(width, height, false);
        session->presenter.reset();
    });
}

EMSCRIPTEN_KEEPALIVE int wb_pan(int dx, int dy) {
    return operation([&] { session->tui.move_viewport(dx, dy); });
}

EMSCRIPTEN_KEEPALIVE int wb_overview() {
    return operation([&] {
        build_overview(*session);
        const auto& data = session->overview_geometry;
        result.assign(reinterpret_cast<const char*>(data.data()), data.size() * sizeof(float));
    });
}

EMSCRIPTEN_KEEPALIVE int wb_overview_view() {
    return operation([&] {
        result.clear();
        const auto& projection = session->overview_projection;
        if (!session->overview_valid || !valid_rect(projection.bounds)) return;
        const Rect rect = viewport_rect(session->tui.viewport());
        const double coordinates[]{projection.x(rect.left), projection.y(rect.top),
                                   projection.x(rect.right), projection.y(rect.bottom)};
        result.assign(reinterpret_cast<const char*>(coordinates), sizeof(coordinates));
    });
}

EMSCRIPTEN_KEEPALIVE int wb_overview_center(double x, double y) {
    return operation([&] {
        if (!session->overview_valid || session->overview_revision != session->tui.app().revision)
            throw std::runtime_error("小地圖正在更新，請稍後再試");
        const Pos position = session->overview_projection.world(x, y);
        session->tui.center_viewport(position);
    });
}

EMSCRIPTEN_KEEPALIVE int wb_reset_input() {
    return operation([&] {
        session->decoder = InputDecoder{};
        session->tui.reset_interaction();
        session->save_requested = false;
    });
}

EMSCRIPTEN_KEEPALIVE int wb_open(const char* bytes, std::size_t size) {
    return operation([&] {
        if (size > kMaximumFileBytes) throw std::runtime_error("file exceeds 32 MiB");
        StringViewInputStream input{{bytes, size}};
        if (!session->tui.app().load(input, size, kDecodeBudget))
            throw std::runtime_error(session->tui.app().file_error);
        session->decoder = InputDecoder{};
        session->tui.reset_interaction();
        session->save_requested = false;
        session->presenter.reset();
        session->tui.set_message("loaded");
        session->overview_valid = false;
    });
}

EMSCRIPTEN_KEEPALIVE int wb_export() {
    return operation([&] {
        std::ostringstream output(std::ios::binary);
        auto& app = session->tui.app();
        if (!whiteboard::io::encode_project(output, app.board, app.glyphs, &error))
            throw std::runtime_error(error);
        result = std::move(output).str();
        if (result.size() > kMaximumFileBytes) {
            result.clear();
            throw std::runtime_error("document exceeds the browser's 32 MiB file limit");
        }
    });
}

EMSCRIPTEN_KEEPALIVE int wb_mark_saved(const char* bytes, std::size_t size) {
    return operation([&] {
        u64 revision = 0;
        const auto parsed = std::from_chars(bytes, bytes + size, revision);
        if (parsed.ec != std::errc{} || parsed.ptr != bytes + size)
            throw std::runtime_error("invalid save revision");
        session->tui.app().mark_saved(revision);
    });
}

EMSCRIPTEN_KEEPALIVE int wb_frame() {
    return operation([&] {
        session->tui.render();
        result = session->presenter.compose(session->tui.app().screen, session->tui.status());
    });
}

EMSCRIPTEN_KEEPALIVE int wb_state() {
    return operation([&] {
        const auto& app = session->tui.app();
        const auto& view = session->tui.viewport();
        std::ostringstream output;
        output << "{\"revision\":\"" << app.revision
               << "\",\"dirty\":" << (app.dirty() ? "true" : "false")
               << ",\"cards\":" << app.board.live_cards
               << ",\"edges\":" << app.board.live_edges
               << ",\"x\":\"" << view.x << "\",\"y\":\"" << view.y
               << "\",\"columns\":" << view.width << ",\"rows\":" << view.height + 1
               << ",\"saveRequested\":" << (session->save_requested ? "true" : "false") << '}';
        session->save_requested = false;
        result = std::move(output).str();
    });
}
}
