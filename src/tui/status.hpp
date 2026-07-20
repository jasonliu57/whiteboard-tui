#pragma once

#include "edge_mode.hpp"
#include "tui.hpp"

#include <string>
#include <string_view>

inline std::string_view Tui::status() {
    std::string& result = status_buffer_;
    result.clear();

    if (app_.session.active == kNoCard) {
        if (board_mode_ == BoardMode::Glyph) {
            if (glyph_mode_.phase == GlyphPhase::Draw) {
                result = " GLYPH DRAW ";
            } else if (glyph_mode_.phase == GlyphPhase::Select) {
                result = " GLYPH SELECT ";
            } else {
                result = " GLYPH PLACE ";
            }

            if (glyph_mode_.phase != GlyphPhase::Draw) {
                append_decimal(result, glyph_mode_.anchor.x);
                result.push_back(',');
                append_decimal(result, glyph_mode_.anchor.y);
                result.append(" -> ");
            }

            append_decimal(result, board_cursor_.x);
            result.push_back(',');
            append_decimal(result, board_cursor_.y);
            result.append(" cells:");
            append_decimal(result, app_.glyphs.cells.size());
            result.append(input_context_help(input_context()));
        } else if (board_mode_ == BoardMode::Edge) {
            switch (edge_mode_.phase) {
                case EdgePhase::Browse:
                    result = " EDGE ";
                    append_decimal(result, board_cursor_.x);
                    result.push_back(',');
                    append_decimal(result, board_cursor_.y);

                    if (edge_mode_.selected != kNoEdge) {
                        const Edge& edge = app_.board.get_edge(
                            edge_mode_.selected
                        );
                        result.append(" edge:");
                        append_decimal(result, edge_mode_.selected);
                        result.append(
                            edge.state == RouteState::Ready
                                ? ":ready"
                                : ":blocked"
                        );

                        if (
                            edge_mode_.segment != kNoEdgeSegment
                        ) {
                            result.append(" segment:");
                            append_decimal(result, edge_mode_.segment);
                        }
                    }

                    result.append(input_context_help(
                        InputContext::EdgeBrowse
                    ));
                    break;

                case EdgePhase::PickTarget:
                    result = " EDGE BUILD source:";
                    append_decimal(result, edge_mode_.source.card);
                    result.push_back(':');
                    result.append(port_side_name(
                        edge_mode_.source.side
                    ));
                    result.append(
                        edge_mode_.build_mode ==
                                EdgeBuildMode::Automatic
                            ? " auto"
                            : (edge_mode_.horizontal_first
                                ? " manual-H"
                                : " manual-V")
                    );
                    result.append(" waypoint:");
                    append_decimal(
                        result,
                        edge_mode_.prefix_undo.size()
                    );

                    if (edge_mode_.target_ready) {
                        result.append(" target:");
                        append_decimal(
                            result,
                            edge_mode_.prepared.target.card
                        );
                        result.push_back(':');
                        result.append(port_side_name(
                            edge_mode_.prepared.target.side
                        ));
                    }

                    result.append(
                        edge_mode_.preview_valid
                            ? (edge_mode_.target_ready
                                ? " | Enter create"
                                : " | Enter waypoint")
                            : (!edge_mode_.target_ready &&
                               edge_mode_.prepared.points ==
                                   edge_mode_.fixed_points
                                ? " | move cursor"
                                : " | blocked")
                    );
                    break;

                case EdgePhase::EditSegment:
                    result = " EDGE EDIT edge:";
                    append_decimal(result, edge_mode_.selected);
                    result.append(" segment:");
                    append_decimal(result, edge_mode_.segment);
                    result.append(
                        edge_mode_.preview_valid
                            ? " | Enter commit, Esc cancel"
                            : " | blocked, Esc cancel"
                    );
                    break;
            }
        } else if (board_mode_ == BoardMode::Select) {
            result = " SELECT card:";
            append_decimal(result, selected_card_);
            result.push_back(':');
            result.append(app_.card_format_name(selected_card_));
        } else {
            result = " BOARD ";
            append_decimal(result, board_cursor_.x);
            result.push_back(',');
            append_decimal(result, board_cursor_.y);

            const CardId id = frame_hovered_;

            if (id != kNoCard) {
                result.append(" card:");
                append_decimal(result, id);
                result.push_back(':');
                result.append(app_.card_format_name(id));
            }
        }
    } else {
        result = " ACTIVE card:";
        append_decimal(result, app_.session.active);
        result.push_back(':');
        result.append(
            app_.card_format_name(app_.session.active)
        );

        if (const auto* text =
                std::get_if<TextSession>(&app_.session.state)) {
            result.append(" row:");
            append_decimal(result, text->cursor.row + 1);
            result.append(" byte:");
            append_decimal(result, text->cursor.byte);
        } else if (const auto* todo =
                std::get_if<TodoSession>(&app_.session.state)) {
            result.append(" item:");
            append_decimal(result, todo->selected_item + 1);
        } else if (const auto* csv =
                std::get_if<CsvSession>(&app_.session.state)) {
            result.append(" cell:");
            append_decimal(result, csv->row + 1);
            result.push_back(',');
            append_decimal(result, csv->column + 1);
        } else if (const auto* folder =
                std::get_if<FolderSession>(&app_.session.state)) {
            if (folder->selected_entry == kNoFolderEntry) {
                result.append(" root");
            } else {
                result.append(" entry:");
                append_decimal(result, folder->selected_entry + 1);
            }
        }
    }

    result.append(app_.dirty() ? " * " : " - ");
    result.append(main_file_);

    if (!message_.empty()) {
        result.append(" | ");
        result.append(message_);
    }

    if (host_.status) host_.status(host_.context, result);
    return result;
}
