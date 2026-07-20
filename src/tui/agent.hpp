#pragma once

#include "../render/thumbnail.hpp"
#include "../storage/api.hpp"
#include "../storage/string_view_stream.hpp"
#include "../verification/canonical_snapshot.hpp"
#include "input.hpp"
#include "native.hpp"

#include <absl/container/inlined_vector.h>

#include <algorithm>
#include <array>
#include <charconv>
#include <limits>
#include <string>
#include <utility>

static bool agent_response_fits(
    std::size_t current,
    std::size_t additional,
    std::size_t trailing = 0
) noexcept {
    if (
        current > kAgentResponseLimit ||
        additional > kAgentResponseLimit - current
    ) {
        return false;
    }

    current += additional;
    return trailing <= kAgentResponseLimit - current;
}

static bool valid_agent_text(std::string_view text) {
    return valid_utf8_display_text(text);
}

static StaticFormatId agent_static_format(AgentCardKind kind) {
    switch (kind) {
        case AgentCardKind::Note:
            return kPlainTextNoteStaticFormatId;
        case AgentCardKind::Markdown:
            return kMarkdownStaticFormatId;
        case AgentCardKind::Code:
            return kCodeStaticFormatId;
        case AgentCardKind::Unknown:
            return static_cast<StaticFormatId>(-1);
    }

    return static_cast<StaticFormatId>(-1);
}

static Card make_agent_text_card(const AgentRequest& request) {
    const Pos position{request.x, request.y};
    Card card;

    switch (request.card_kind) {
        case AgentCardKind::Note:
            card = make_plain_text_note(
                position,
                request.width,
                request.height
            );
            break;
        case AgentCardKind::Markdown:
            card = make_markdown_card(
                position,
                request.width,
                request.height
            );
            break;
        case AgentCardKind::Code:
            card = make_code_card(
                position,
                kCppLanguageId,
                request.width,
                request.height
            );
            break;
        case AgentCardKind::Unknown:
            break;
    }

    (void)whiteboard::io::read_card_content(
        request.text,
        card_save_format(card),
        card.data
    );
    TextCardData& data = std::get<TextCardData>(card.data);

    TextSession syntax;
    begin_text_syntax(syntax, data);
    return card;
}

static bool agent_line_space(char ch) {
    return ch == ' ' || ch == '\t' || ch == '\r';
}

static bool next_agent_line_word(
    std::string_view line,
    std::size_t& offset,
    std::string_view& word
) {
    while (offset < line.size() && agent_line_space(line[offset])) {
        ++offset;
    }

    if (offset == line.size()) {
        return false;
    }

    const std::size_t begin = offset;

    while (offset < line.size() && !agent_line_space(line[offset])) {
        ++offset;
    }

    word = line.substr(begin, offset - begin);
    return true;
}

template<class Integer>
static bool parse_agent_integer(
    std::string_view text,
    Integer& value
) {
    const auto [end, error] = std::from_chars(
        text.data(),
        text.data() + text.size(),
        value
    );
    return error == std::errc{} && end == text.data() + text.size();
}

static bool parse_agent_folder_entry(
    std::string_view line,
    FolderEntry& entry
) {
    std::array<std::string_view, 5> fields;
    std::size_t begin = 0;

    for (std::size_t i = 0; i + 1 < fields.size(); ++i) {
        const std::size_t end = line.find('\t', begin);

        if (end == std::string_view::npos) {
            return false;
        }

        fields[i] = line.substr(begin, end - begin);
        begin = end + 1;
    }

    fields.back() = line.substr(begin);
    u32 depth = 0;
    CardId target = kNoCard;
    bool collapsed = false;
    FolderEntryKind kind;

    if (!parse_agent_integer(fields[0], depth)) {
        return false;
    }

    if (fields[1] == "DIR") {
        if (fields[2] != "-") {
            return false;
        }

        kind = FolderEntryKind::Directory;
    } else if (fields[1] == "CARD") {
        if (!parse_agent_integer(fields[2], target)) {
            return false;
        }

        kind = FolderEntryKind::Card;
    } else {
        return false;
    }

    if (fields[3] == "1") {
        collapsed = true;
    } else if (fields[3] != "0") {
        return false;
    }

    if (kind == FolderEntryKind::Card && collapsed) {
        return false;
    }

    entry = {
        .kind = kind,
        .depth = depth,
        .name = std::string{fields[4]},
        .target = target,
        .collapsed = collapsed,
    };
    return true;
}

static bool read_agent_folder_content(
    std::string_view content,
    FolderCardData& data
) {
    data.name.clear();
    data.entries.clear();

    if (content.empty()) {
        return true;
    }

    std::size_t begin = 0;
    const auto next_line = [&](std::size_t& position) {
        const std::size_t end = content.find_first_of("\r\n", position);
        const std::string_view line = content.substr(
            position,
            end == std::string_view::npos
                ? content.size() - position
                : end - position
        );

        if (end == std::string_view::npos) {
            position = content.size();
        } else {
            position = end + 1;

            if (
                content[end] == '\r' &&
                position < content.size() &&
                content[position] == '\n'
            ) {
                ++position;
            }
        }

        return line;
    };
    const std::string_view root = next_line(begin);

    if (!root.starts_with("ROOT\t")) {
        return false;
    }

    data.name.assign(root.substr(5));

    while (begin < content.size()) {
        const std::string_view line = next_line(begin);
        FolderEntry entry;

        if (
            line.empty() ||
            !parse_agent_folder_entry(line, entry)
        ) {
            return false;
        }

        data.entries.push_back(std::move(entry));
    }

    return true;
}

static bool read_agent_card_content(
    const Card& card,
    std::string_view content,
    CardData& data
) {
    if (card_save_format(card) == SaveFormat::FolderTree) {
        return read_agent_folder_content(
            content,
            std::get<FolderCardData>(data)
        );
    }

    return whiteboard::io::read_card_content(
        content,
        card_save_format(card),
        data
    );
}

static Extent agent_card_layout(
    StaticFormatId static_format,
    Extent extent
) {
    if (static_format == kTextArtStaticFormatId) {
        extent.width += 2;
        extent.height += 2;
    }

    return extent;
}

static CardData make_agent_replacement_data(
    const Card& card,
    Extent requested_extent
) {
    const Extent extent = agent_card_layout(
        card.static_format,
        requested_extent
    );

    if (const auto* source = std::get_if<TextCardData>(&card.data)) {
        TextCardData data;
        data.layout = extent;
        data.language = source->language;

        if (card.static_format == kPlainTextNoteStaticFormatId) {
            data.styles = source->styles;
        }

        return data;
    }

    if (const auto* source = std::get_if<TodoCardData>(&card.data)) {
        TodoCardData data;
        data.layout = extent;
        data.items.clear();
        data.items.reserve(source->items.size());

        for (const TodoItem& item : source->items) {
            TodoItem metadata;
            metadata.style = item.style;
            data.items.push_back(std::move(metadata));
        }

        return data;
    }

    if (const auto* source = std::get_if<CsvCardData>(&card.data)) {
        CsvCardData data;
        data.layout = extent;
        data.column_widths = source->column_widths;
        data.styled_cells = source->styled_cells;
        return data;
    }

    FolderCardData data;
    data.layout = extent;
    return data;
}

inline std::string NativeTui::agent_prefix() const {
    std::string response = "OK ";
    append_decimal(response, app_.revision);
    response.push_back(' ');
    return response;
}

inline bool NativeTui::append_agent_card(
    std::string& response,
    CardId id
) const {
    const Card& card = app_.board.get(id);
    const Extent extent = app_.card_extent(id);
    CountingStreamBuffer counter;
    std::ostream counting_output(&counter);

    if (!whiteboard::io::write_exchange_card_content(counting_output, card)) {
        return false;
    }

    const std::size_t begin = response.size();
    response.append("CARD ");
    append_decimal(response, id);
    response.push_back(' ');
    response.append(app_.card_format_name(id));
    response.push_back(' ');
    append_decimal(response, card.pos.x);
    response.push_back(' ');
    append_decimal(response, card.pos.y);
    response.push_back(' ');
    append_decimal(response, extent.width);
    response.push_back(' ');
    append_decimal(response, extent.height);
    response.push_back(' ');
    append_decimal(response, counter.size());
    response.push_back('\n');

    if (!agent_response_fits(response.size(), counter.size(), 1)) {
        response.resize(begin);
        return false;
    }

    response.reserve(response.size() + counter.size() + 1);
    StringAppendOutputStream output(response);

    if (!whiteboard::io::write_exchange_card_content(output, card)) {
        response.resize(begin);
        return false;
    }

    response.push_back('\n');
    return true;
}

inline std::string NativeTui::agent_status_response() const {
    std::string response = agent_prefix();
    response.append("STATUS ");
    append_decimal(response, app_.board.live_cards);
    response.push_back(' ');
    append_decimal(response, app_.board.live_edges);
    response.push_back(' ');
    response.append(app_.dirty() ? "1\n" : "0\n");
    return response;
}

inline std::string NativeTui::agent_view_response() const {
    std::string_view mode = "BOARD";

    if (app_.session.active != kNoCard) {
        mode = "ACTIVE";
    } else if (board_mode_ == BoardMode::Select) {
        mode = "SELECT";
    } else if (board_mode_ == BoardMode::Edge) {
        mode = "EDGE";
    } else if (board_mode_ == BoardMode::Glyph) {
        mode = "GLYPH";
    }

    const CardId selected = app_.session.active != kNoCard
        ? app_.session.active
        : (board_mode_ == BoardMode::Select
            ? selected_card_
            : kNoCard);
    std::string response = agent_prefix();
    response.append("VIEW ");
    response.append(mode);
    response.push_back(' ');
    append_decimal(response, viewport_.x);
    response.push_back(' ');
    append_decimal(response, viewport_.y);
    response.push_back(' ');
    append_decimal(response, viewport_.width);
    response.push_back(' ');
    append_decimal(response, viewport_.height);
    response.push_back(' ');
    append_decimal(response, board_cursor_.x);
    response.push_back(' ');
    append_decimal(response, board_cursor_.y);
    response.push_back(' ');

    if (selected == kNoCard) {
        response.push_back('-');
    } else {
        append_decimal(response, selected);
    }

    response.push_back('\n');
    return response;
}

inline std::string NativeTui::agent_screen_text_response() const {
    const std::size_t body_size = text_screenshot_size(
        app_.screen,
        status_buffer_
    );
    std::string response = agent_prefix();
    response.append("SCREEN_TEXT ");
    append_decimal(response, app_.screen.width());
    response.push_back(' ');
    append_decimal(response, app_.screen.height() + 1);
    response.push_back(' ');
    append_decimal(response, body_size);
    response.push_back('\n');

    if (!agent_response_fits(response.size(), body_size)) {
        return "ERR response_too_large\n";
    }

    append_text_screenshot(
        response,
        app_.screen,
        status_buffer_,
        body_size
    );
    return response;
}

inline std::string NativeTui::agent_screen_png_response(u32 font_pixels) const {
    PngScreenshot image;

    if (!png_screenshot(
            app_.screen,
            status_buffer_,
            font_pixels,
            image
        )) {
        return "ERR screenshot_failed\n";
    }

    std::string response = agent_prefix();
    response.append("SCREEN_PNG ");
    append_decimal(response, image.width);
    response.push_back(' ');
    append_decimal(response, image.height);
    response.push_back(' ');
    append_decimal(response, image.bytes.size());
    response.push_back('\n');

    if (!agent_response_fits(response.size(), image.bytes.size())) {
        return "ERR response_too_large\n";
    }

    response.reserve(response.size() + image.bytes.size());
    response.append(image.bytes);
    return response;
}

inline std::string NativeTui::agent_board_png_response(
    u32 max_side,
    AgentBoardLabel label,
    bool show_viewport
) const {
    BoardThumbnailLabel thumbnail_label = BoardThumbnailLabel::Name;

    if (label == AgentBoardLabel::Format) {
        thumbnail_label = BoardThumbnailLabel::Format;
    } else if (label == AgentBoardLabel::CardId) {
        thumbnail_label = BoardThumbnailLabel::CardId;
    }

    const Rect viewport = viewport_rect(viewport_);
    PngScreenshot image;
    const BoardThumbnailResult result = board_thumbnail_png(
        app_.board,
        app_.spatial,
        app_.formats,
        max_side,
        thumbnail_label,
        show_viewport ? &viewport : nullptr,
        image
    );

    if (result == BoardThumbnailResult::Empty) {
        return "ERR empty_board\n";
    }

    if (result != BoardThumbnailResult::Success) {
        return "ERR thumbnail_failed\n";
    }

    std::string response = agent_prefix();
    response.append("BOARD_PNG ");
    append_decimal(response, image.width);
    response.push_back(' ');
    append_decimal(response, image.height);
    response.push_back(' ');
    append_decimal(response, image.bytes.size());
    response.push_back('\n');

    if (!agent_response_fits(response.size(), image.bytes.size())) {
        return "ERR response_too_large\n";
    }

    response.reserve(response.size() + image.bytes.size());
    response.append(image.bytes);
    return response;
}

inline std::string NativeTui::agent_snapshot_response(
    const AgentRequest& request
) const {
    if (
        request.snapshot_revision_set &&
        request.expected_revision != app_.revision
    ) {
        std::string response = "ERR stale_revision ";
        append_decimal(response, app_.revision);
        response.push_back('\n');
        return response;
    }

    const whiteboard::verification::CanonicalSnapshotCursor cursor{
        .card = request.snapshot_card_cursor,
        .edge = request.snapshot_edge_cursor,
        .glyph = request.snapshot_glyph_cursor,
    };
    whiteboard::verification::CanonicalSnapshotPage page;
    const auto result =
        whiteboard::verification::make_canonical_snapshot_page(
            app_.board,
            app_.spatial,
            app_.glyphs,
            app_.formats,
            cursor,
            kAgentResponseLimit - kAgentHeaderLimit,
            page
        );

    if (
        result == whiteboard::verification::
            CanonicalSnapshotResult::InvalidCursor
    ) {
        return "ERR invalid_snapshot_cursor\n";
    }

    if (
        result == whiteboard::verification::
            CanonicalSnapshotResult::RecordTooLarge
    ) {
        return "ERR response_too_large\n";
    }

    if (
        result != whiteboard::verification::
            CanonicalSnapshotResult::Success
    ) {
        return "ERR snapshot_failed\n";
    }

    std::string response = agent_prefix();
    response.append("SNAPSHOT ");
    append_decimal(response, kAgentProtocolVersion);
    response.push_back(' ');
    append_decimal(response, page.next.card);
    response.push_back(' ');
    append_decimal(response, page.next.edge);
    response.push_back(' ');
    append_decimal(response, page.next.glyph);
    response.push_back(' ');
    response.push_back(page.done ? '1' : '0');
    response.push_back(' ');
    append_decimal(response, page.body.size());
    response.push_back('\n');

    if (!agent_response_fits(response.size(), page.body.size())) {
        return "ERR response_too_large\n";
    }

    response.append(page.body);
    return response;
}

inline std::string NativeTui::agent_get_card_response(CardId id) const {
    if (!app_.has_card(id)) {
        return "ERR missing_card\n";
    }

    std::string response = agent_prefix();

    if (!append_agent_card(response, id)) {
        return "ERR response_too_large\n";
    }

    response.append("END\n");
    return response;
}

inline std::string NativeTui::agent_query_response(const AgentRequest& request) const {
    std::array<CardId, kAgentQueryLimit> cards{};
    std::size_t count = 0;
    app_.spatial.query(
        {request.left, request.top, request.right, request.bottom},
        [&](CardId id) {
            cards[count++] = id;
            return count < request.limit;
        }
    );

    std::string response = agent_prefix();
    response.append("QUERY ");
    append_decimal(response, count);
    response.push_back('\n');

    for (std::size_t i = 0; i < count; ++i) {
        if (!append_agent_card(response, cards[i])) {
            return "ERR response_too_large\n";
        }
    }

    response.append("END\n");
    return response;
}

inline std::string NativeTui::agent_edges_response(CardId card) const {
    if (!app_.has_card(card)) {
        return "ERR missing_card\n";
    }

    std::string response = agent_prefix();
    response.append("EDGES ");
    append_decimal(response, card);
    response.push_back(' ');
    append_decimal(response, app_.board.incident[card].size());
    response.push_back('\n');

    std::string line;

    for (EdgeId id : app_.board.incident[card]) {
        const Edge& edge = app_.board.get_edge(id);

        line.clear();
        line.append("EDGE ");
        append_decimal(line, id);
        line.push_back(' ');
        append_decimal(line, edge.source.card);
        line.push_back(' ');
        append_decimal(line, static_cast<u8>(edge.source.side));
        line.push_back(' ');
        append_decimal(line, edge.target.card);
        line.push_back(' ');
        append_decimal(line, static_cast<u8>(edge.target.side));
        line.push_back(' ');
        append_decimal(line, static_cast<u8>(edge.mode));
        line.push_back(' ');
        append_decimal(line, static_cast<u8>(edge.state));
        line.push_back(' ');
        append_decimal(line, edge.route_bounds.left);
        line.push_back(' ');
        append_decimal(line, edge.route_bounds.top);
        line.push_back(' ');
        append_decimal(line, edge.route_bounds.right);
        line.push_back(' ');
        append_decimal(line, edge.route_bounds.bottom);
        line.push_back(' ');
        append_decimal(line, edge.points.size());
        line.push_back('\n');

        for (Pos point : edge.points) {
            line.append("POINT ");
            append_decimal(line, point.x);
            line.push_back(' ');
            append_decimal(line, point.y);
            line.push_back('\n');
        }

        if (!agent_response_fits(response.size(), line.size())) {
            return "ERR response_too_large\n";
        }

        response.append(line);
    }

    response.append("END\n");
    return response;
}

inline const AgentProposalResult* NativeTui::find_agent_proposal_result(u64 id) const {
    for (std::size_t i = 0;
         i < agent_proposal_result_count_;
         ++i) {
        const AgentProposalResult& result = agent_proposal_results_[i];

        if (result.id == id) {
            return &result;
        }
    }

    return nullptr;
}

inline std::string NativeTui::agent_proposal_status_response(u64 id) const {
    std::string response = agent_prefix();
    response.append("PROPOSAL ");
    append_decimal(response, id);
    response.push_back(' ');

    if (
        pending_agent_proposal_.has_value() &&
        pending_agent_proposal_->id == id
    ) {
        response.append("PENDING\n");
        return response;
    }

    const AgentProposalResult* result =
        find_agent_proposal_result(id);

    if (result == nullptr) {
        return "ERR missing_proposal\n";
    }

    if (result->state == AgentProposalState::Rejected) {
        response.append("REJECTED\n");
    } else {
        response.append("COMMITTED ");
        append_decimal(response, result->card);
        response.push_back('\n');
    }

    return response;
}

inline bool NativeTui::begin_agent_proposal(
    const AgentRequest& request,
    std::string& response
) {
    if (pending_agent_proposal_.has_value()) {
        response = "ERR proposal_busy\n";
        return false;
    }

    const StaticFormatId static_format =
        agent_static_format(request.card_kind);

    if (static_format >= app_.formats.size()) {
        response = "ERR invalid_proposal\n";
        return false;
    }

    const CardFormat& format = app_.formats[static_format];
    const Extent extent{request.width, request.height};
    Rect unused;

    if (
        extent.width < format.minimum_layout.width ||
        extent.width > format.maximum_layout.width ||
        extent.height < format.minimum_layout.height ||
        extent.height > format.maximum_layout.height ||
        !valid_agent_text(request.text) ||
        !checked_rect_at({request.x, request.y}, extent, unused)
    ) {
        response = "ERR invalid_proposal\n";
        return false;
    }

    const u64 id = next_agent_proposal_++;
    pending_agent_proposal_.emplace(PendingAgentProposal{
        .id = id,
        .card = make_agent_text_card(request),
    });
    response = agent_prefix();
    response.append("PROPOSAL ");
    append_decimal(response, id);
    response.append(" PENDING\n");
    message_ = "agent proposal:";
    append_decimal(message_, id);
    return true;
}

static bool agent_revision_current(
    u64 expected,
    u64 current,
    std::string& response
);

inline bool NativeTui::create_agent_cards(
    const AgentRequest& request,
    std::string& response
) {
    if (
        request.mutation_revision_set &&
        !agent_revision_current(
            request.expected_revision,
            app_.revision,
            response
        )
    ) {
        return false;
    }

    std::vector<Card> cards;
    u32 invalid_line = 0;
    const RegisteredCardBatchResult batch = build_registered_card_batch(
        app_.formats,
        request.text,
        cards,
        invalid_line
    );

    if (batch == RegisteredCardBatchResult::Empty) {
        response = "ERR empty_card_batch\n";
        return false;
    }

    if (batch == RegisteredCardBatchResult::InvalidLine) {
        response = "ERR invalid_card_line ";
        append_decimal(response, invalid_line);
        response.push_back('\n');
        return false;
    }

    const std::size_t count = cards.size();
    const CardId first = app_.add_cards(std::move(cards));

    if (first == kNoCard) {
        response = "ERR invalid_card_batch\n";
        return false;
    }

    response = agent_prefix();
    response.append("CREATE_CARDS ");
    append_decimal(response, count);
    response.push_back(' ');
    append_decimal(response, first);
    response.push_back('\n');
    message_ = "agent created ";
    append_decimal(message_, count);
    message_.append(" cards");
    return true;
}

static bool agent_revision_current(
    u64 expected,
    u64 current,
    std::string& response
) {
    if (expected == current) {
        return true;
    }

    response = "ERR stale_revision ";
    append_decimal(response, current);
    response.push_back('\n');
    return false;
}

inline bool NativeTui::replace_agent_card(
    const AgentRequest& request,
    std::string& response
) {
    if (!app_.has_card(request.card)) {
        response = "ERR missing_card\n";
        return false;
    }

    if (!agent_revision_current(
            request.expected_revision,
            app_.revision,
            response
        )) {
        return false;
    }

    const Card& card = app_.board.get(request.card);
    const CardFormat& format = app_.formats[card.static_format];
    const Extent extent{request.width, request.height};
    Rect unused;

    if (
        extent.width < format.minimum_layout.width ||
        extent.width > format.maximum_layout.width ||
        extent.height < format.minimum_layout.height ||
        extent.height > format.maximum_layout.height ||
        !checked_rect_at(card.pos, extent, unused)
    ) {
        response = "ERR invalid_layout\n";
        return false;
    }

    if (!valid_agent_text(request.text)) {
        response = "ERR invalid_content\n";
        return false;
    }

    CardData replacement = make_agent_replacement_data(card, extent);

    if (!read_agent_card_content(
            card,
            request.text,
            replacement
        )) {
        response = "ERR invalid_content\n";
        return false;
    }

    format.rebuild(replacement);

    if (TextCardData* text =
            std::get_if<TextCardData>(&replacement)) {
        TextSession syntax;
        begin_text_syntax(syntax, *text);
    }

    if (!app_.replace_card(request.card, std::move(replacement))) {
        response = "ERR invalid_layout\n";
        return false;
    }
    response = agent_prefix();
    response.append("REPLACE_CARD ");
    append_decimal(response, request.card);
    response.push_back('\n');
    message_ = "agent replaced card:";
    append_decimal(message_, request.card);
    return true;
}

inline bool NativeTui::delete_agent_cards(
    const AgentRequest& request,
    std::string& response
) {
    absl::InlinedVector<CardId, 16> cards;

    if (request.operation == AgentOperation::DeleteCard) {
        cards.push_back(request.card);
    } else {
        u32 line_number = 0;

        for (std::size_t begin = 0;
             begin < request.text.size();) {
            std::size_t end = request.text.find('\n', begin);

            if (end == std::string::npos) {
                end = request.text.size();
            }

            ++line_number;
            const std::string_view line{
                request.text.data() + begin,
                end - begin,
            };
            std::size_t offset = 0;
            std::string_view word;

            if (next_agent_line_word(line, offset, word)) {
                CardId id = kNoCard;
                std::string_view extra;

                if (
                    !parse_agent_integer(word, id) ||
                    next_agent_line_word(line, offset, extra)
                ) {
                    response = "ERR invalid_card_id_line ";
                    append_decimal(response, line_number);
                    response.push_back('\n');
                    return false;
                }

                cards.push_back(id);
            }

            begin = end + 1;
        }
    }

    if (cards.empty()) {
        response = "ERR empty_card_delete\n";
        return false;
    }

    std::sort(cards.begin(), cards.end());

    for (std::size_t i = 0; i < cards.size(); ++i) {
        if (i != 0 && cards[i] == cards[i - 1]) {
            response = "ERR duplicate_card ";
            append_decimal(response, cards[i]);
            response.push_back('\n');
            return false;
        }

        if (!app_.has_card(cards[i])) {
            response = "ERR missing_card ";
            append_decimal(response, cards[i]);
            response.push_back('\n');
            return false;
        }
    }

    if (!agent_revision_current(
            request.expected_revision,
            app_.revision,
            response
        )) {
        return false;
    }

    if (!app_.erase_cards(cards.data(), cards.size())) {
        response = "ERR invalid_card_delete_batch\n";
        return false;
    }

    if (
        exporting_folder_ != kNoCard &&
        !app_.has_card(exporting_folder_)
    ) {
        exporting_folder_ = kNoCard;
        export_parent_.clear();
    }

    card_dragging_ = false;
    edit_card_on_release_ = false;
    normalize_board_mode();
    response = agent_prefix();

    if (request.operation == AgentOperation::DeleteCard) {
        response.append("DELETE_CARD ");
        append_decimal(response, cards.front());
        message_ = "agent deleted card:";
        append_decimal(message_, cards.front());
    } else {
        response.append("DELETE_CARDS ");
        append_decimal(response, cards.size());
        message_ = "agent deleted ";
        append_decimal(message_, cards.size());
        message_.append(" cards");
    }

    response.push_back('\n');
    return true;
}

static i64 agent_coordinate_midpoint(i64 first, i64 second) {
    return
        first / 2 +
        second / 2 +
        (first % 2 + second % 2) / 2;
}

inline bool NativeTui::connect_agent_cards(
    const AgentRequest& request,
    std::string& response
) {
    if (
        request.mutation_revision_set &&
        !agent_revision_current(
            request.expected_revision,
            app_.revision,
            response
        )
    ) {
        return false;
    }

    if (
        !app_.has_card(request.card) ||
        !app_.has_card(request.target_card)
    ) {
        response = "ERR missing_card\n";
        return false;
    }

    if (request.card == request.target_card) {
        response = "ERR same_card\n";
        return false;
    }

    Edge edge;
    set_facing_edge_ends(
        app_.spatial,
        request.card,
        request.target_card,
        edge
    );
    const PortGeometry source = app_.port_geometry(edge.source);
    const PortGeometry target = app_.port_geometry(edge.target);
    const Pos midpoint{
        agent_coordinate_midpoint(
            source.position.x,
            target.position.x
        ),
        agent_coordinate_midpoint(
            source.position.y,
            target.position.y
        ),
    };

    reset_interaction();
    center_viewport(midpoint);

    if (!app_.route_edge(edge, viewport_rect(viewport_))) {
        response = "ERR no_route_in_view\n";
        message_ = "agent edge has no route in current viewport";
        return true;
    }

    const EdgeId id = app_.add_edge(std::move(edge));

    if (id == kNoEdge) {
        response = "ERR edge_capacity\n";
        message_ = "agent edge capacity reached";
        return true;
    }

    response = agent_prefix();
    response.append("CONNECT ");
    append_decimal(response, id);
    response.push_back('\n');
    message_ = "agent edge created:";
    append_decimal(message_, id);
    return true;
}

inline bool NativeTui::handle_agent_request(AgentRequest request) {
    std::string response;
    bool redraw = false;

    switch (request.operation) {
        case AgentOperation::Status:
            response = agent_status_response();
            break;
        case AgentOperation::View:
            response = agent_view_response();
            break;
        case AgentOperation::ScreenText:
            response = agent_screen_text_response();
            break;
        case AgentOperation::ScreenPng:
            response = agent_screen_png_response(request.png_pixels);
            break;
        case AgentOperation::BoardPng:
            response = agent_board_png_response(
                request.board_png_side,
                request.board_label,
                request.board_viewport
            );
            break;
        case AgentOperation::Snapshot:
            response = agent_snapshot_response(request);
            break;
        case AgentOperation::GetCard:
            response = agent_get_card_response(request.card);
            break;
        case AgentOperation::QueryRect:
            response = agent_query_response(request);
            break;
        case AgentOperation::CardEdges:
            response = agent_edges_response(request.card);
            break;
        case AgentOperation::ProposalStatus:
            response = agent_proposal_status_response(
                request.proposal
            );
            break;
        case AgentOperation::ProposeTextCard:
            redraw = begin_agent_proposal(request, response);
            break;
        case AgentOperation::CreateCards:
            redraw = create_agent_cards(request, response);
            break;
        case AgentOperation::ReplaceCard:
            redraw = replace_agent_card(request, response);
            break;
        case AgentOperation::DeleteCard:
        case AgentOperation::DeleteCards:
            redraw = delete_agent_cards(request, response);
            break;
        case AgentOperation::ConnectCards:
            redraw = connect_agent_cards(request, response);
            break;
    }

    agent_.reply(request.client, std::move(response));
    return redraw;
}

inline void NativeTui::remember_agent_proposal(AgentProposalResult result) {
    agent_proposal_results_[next_agent_proposal_result_] = result;
    next_agent_proposal_result_ =
        (next_agent_proposal_result_ + 1) %
        agent_proposal_results_.size();
    agent_proposal_result_count_ = std::min(
        agent_proposal_result_count_ + 1,
        agent_proposal_results_.size()
    );
}

inline void NativeTui::accept_agent_proposal() {
    if (
        app_.session.active != kNoCard ||
        (board_mode_ != BoardMode::Cursor &&
         board_mode_ != BoardMode::Select)
    ) {
        message_ = "return to board before accepting proposal";
        return;
    }

    PendingAgentProposal proposal =
        std::move(*pending_agent_proposal_);
    pending_agent_proposal_.reset();
    const CardId id = app_.add_card(std::move(proposal.card));

    if (id == kNoCard) {
        remember_agent_proposal({
            .id = proposal.id,
            .state = AgentProposalState::Rejected,
            .card = kNoCard,
        });
        message_ = "agent proposal invalid";
        return;
    }

    remember_agent_proposal({
        .id = proposal.id,
        .state = AgentProposalState::Committed,
        .card = id,
    });
    message_ = "agent card committed:";
    append_decimal(message_, id);
}

inline void NativeTui::reject_agent_proposal() {
    const u64 id = pending_agent_proposal_->id;
    pending_agent_proposal_.reset();
    remember_agent_proposal({
        .id = id,
        .state = AgentProposalState::Rejected,
        .card = kNoCard,
    });
    message_ = "agent proposal rejected:";
    append_decimal(message_, id);
}
