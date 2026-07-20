#pragma once

#include "keymap.hpp"
#include "tui.hpp"

#include <string_view>

inline InputContext Tui::input_context() const {
    if (app_.session.active != kNoCard) {
        return InputContext::ActiveCard;
    }

    switch (board_mode_) {
        case BoardMode::Cursor:
            return InputContext::BoardCursor;

        case BoardMode::Select:
            return InputContext::BoardSelect;

        case BoardMode::Glyph:
            switch (glyph_mode_.phase) {
                case GlyphPhase::Draw:
                    return InputContext::GlyphDraw;
                case GlyphPhase::Select:
                    return InputContext::GlyphSelect;
                case GlyphPhase::Place:
                    return InputContext::GlyphPlace;
            }
            break;

        case BoardMode::Edge:
            switch (edge_mode_.phase) {
                case EdgePhase::Browse:
                    return InputContext::EdgeBrowse;
                case EdgePhase::PickTarget:
                    return InputContext::EdgeBuild;
                case EdgePhase::EditSegment:
                    return InputContext::EdgeEdit;
            }
            break;
    }

    return InputContext::BoardCursor;
}

inline bool Tui::handle(InputEvent& event) {
    if (host_.input && host_.input(host_.context, event)) return true;
    if (event.mouse != MouseAction::None) {
        return handle_board_mouse(event);
    }

    card_dragging_ = false;
    edit_card_on_release_ = false;
    middle_dragging_ = false;

    InputContext context = input_context();

    if (event.key == Key::Text) {
        if (context == InputContext::ActiveCard) {
            return handle_active_event(event);
        }

        if (context == InputContext::GlyphDraw) {
            return draw_glyph_text(event.text);
        }

        return route_text_commands(event);
    }

    if (const Binding* binding =
            resolve_context_binding(context, event)) {
        return dispatch(binding->action);
    }

    if (const Binding* binding = resolve_binding(
            kGlobalBindings,
            kGlobalBindingCount,
            event
        )) {
        return dispatch(binding->action);
    }

    if (context == InputContext::ActiveCard) {
        return handle_active_event(event);
    }

    if (
        event.key == Key::Paste &&
        context == InputContext::GlyphDraw
    ) {
        return draw_glyph_text(event.text);
    }

    if (
        event.key == Key::Paste &&
        (context == InputContext::GlyphSelect ||
         context == InputContext::GlyphPlace)
    ) {
        return route_text_commands(event);
    }

    return false;
}

inline bool Tui::route_text_commands(InputEvent& event) {
    bool redraw = false;
    const std::string_view text = event.text;

    for (u32 byte = 0; byte < text.size();) {
        const InputContext context = input_context();

        if (host_.modal && host_.modal(host_.context)) {
            InputEvent remainder = event;
            remainder.text = text.substr(byte);
            return host_.input(host_.context, remainder) || redraw;
        }

        if (context == InputContext::ActiveCard) {
            event.text.erase(0, byte);
            return handle_active_event(event) || redraw;
        }

        if (context == InputContext::GlyphDraw) {
            return draw_glyph_text(text.substr(byte)) || redraw;
        }

        const Rune rune = decode_utf8(text, byte);
        const InputEvent command{
            .key = Key::Text,
            .text = {},
            .shift = false,
            .ctrl = false,
        };
        const Binding* binding = resolve_context_binding(
            context,
            command,
            rune.codepoint
        );

        byte += rune.bytes;

        if (binding == nullptr) {
            continue;
        }

        redraw = dispatch(binding->action) || redraw;
    }

    return redraw;
}

inline bool Tui::dispatch(TuiAction action) {
    i64 dx = 0;
    i64 dy = 0;
    const InputContext context = input_context();
    const bool moves = move_action(action);
    const bool pans = pan_action(action);
    const bool selects_corner = corner_action(action);
    const bool moves_card = move_card_action(action);
    const bool steps_glyph = glyph_step_action(action);

    if (
        moves || pans || selects_corner ||
        moves_card || steps_glyph
    ) {
        action_direction(action, dx, dy);
    }

    if (moves) {
        switch (context) {
            case InputContext::BoardCursor:
            case InputContext::BoardSelect:
                move_board_focus(dx, dy);
                break;

            case InputContext::GlyphDraw:
            case InputContext::GlyphSelect:
                move_board_cursor(dx, dy);
                break;

            case InputContext::GlyphPlace:
                move_glyph_placement(dx, dy);
                break;

            case InputContext::EdgeBrowse:
            case InputContext::EdgeBuild:
            case InputContext::EdgeEdit:
                move_edge_cursor(dx, dy);
                break;

            default:
                return false;
        }

        return true;
    }

    if (pans) {
        switch (context) {
            case InputContext::BoardCursor:
            case InputContext::BoardSelect:
                move_viewport(dx, dy);
                break;

            case InputContext::GlyphDraw:
            case InputContext::GlyphPlace:
                move_glyph_viewport(dx, dy);
                break;

            case InputContext::EdgeBrowse:
            case InputContext::EdgeBuild:
            case InputContext::EdgeEdit:
                move_viewport(dx, dy);
                update_edge_preview();
                break;

            default:
                return false;
        }

        return true;
    }

    if (selects_corner) {
        select_glyph_corner(dx, dy);
        return true;
    }

    if (moves_card) {
        move_card(dx, dy);
        return true;
    }

    if (steps_glyph) {
        if (context == InputContext::GlyphSelect) {
            begin_glyph_placement(dx, dy);
        } else {
            move_glyph_placement(dx, dy);
        }
        return true;
    }

    switch (action) {
        case TuiAction::AcceptProposal:
        case TuiAction::RejectProposal:
        case TuiAction::Save:
        case TuiAction::ForceQuit:
        case TuiAction::QuitClean:
        case TuiAction::BeginFolderExport:
        case TuiAction::CancelExport:
        case TuiAction::CommitExport:
        case TuiAction::ExportBackspace:
            return host_.command(host_.context, action);

        case TuiAction::Undo:
            message_ = app_.undo() ? "undo" : "nothing to undo";
            normalize_board_mode();
            return true;

        case TuiAction::Redo:
            message_ = app_.redo() ? "redo" : "nothing to redo";
            normalize_board_mode();
            return true;

        case TuiAction::RejectUndo:
            message_ = "glyph mode has no undo";
            return true;

        case TuiAction::RejectRedo:
            message_ = "glyph mode has no redo";
            return true;

        case TuiAction::LeaveActiveCard:
            selected_card_ = app_.session.active;
            board_mode_ = BoardMode::Select;
            app_.end_card();
            message_ = "selected";
            return true;

        case TuiAction::EnterSelection:
            enter_selection();
            return true;

        case TuiAction::LeaveSelection:
            leave_selection();
            return true;

        case TuiAction::BoardHome:
            board_cursor_ = {};
            keep_board_cursor_visible();
            return true;

        case TuiAction::BoardPageUp:
            move_board_cursor(0, -viewport_.height);
            return true;

        case TuiAction::BoardPageDown:
            move_board_cursor(0, viewport_.height);
            return true;

        case TuiAction::EditCard:
            edit_card();
            return true;

        case TuiAction::DeleteCard:
            erase_card();
            return true;

        case TuiAction::CopyCard:
            copy_card();
            return true;

        case TuiAction::CutCard:
            cut_card();
            return true;

        case TuiAction::PasteCard:
            paste_card();
            return true;

        case TuiAction::RejectTextPaste:
            message_ = "paste text only in active card";
            return true;

        case TuiAction::ConvertTextArtGlyphs:
            convert_text_art_glyphs();
            return true;

        case TuiAction::CreateNote:
            new_note();
            return true;

        case TuiAction::CreateMarkdown:
            new_markdown();
            return true;

        case TuiAction::CreateCode:
            new_code();
            return true;

        case TuiAction::CreateTodo:
            new_todo();
            return true;

        case TuiAction::CreateCsv:
            new_csv();
            return true;

        case TuiAction::CreateFolder:
            new_folder();
            return true;

        case TuiAction::BeginEdge:
            begin_edge_mode();
            return true;

        case TuiAction::BeginGlyph:
            begin_glyph_mode();
            return true;

        case TuiAction::GlyphTab:
            if (glyph_mode_.phase == GlyphPhase::Place) {
                message_ = "Enter place, Esc cancel";
            } else {
                toggle_glyph_selection();
            }
            return true;

        case TuiAction::GlyphEnter:
            if (glyph_mode_.phase == GlyphPhase::Place) {
                commit_glyph_placement();
            } else if (glyph_mode_.phase == GlyphPhase::Select) {
                toggle_glyph_selection();
            } else {
                move_board_cursor(0, 1);
            }
            return true;

        case TuiAction::GlyphBackspace:
            if (glyph_mode_.phase == GlyphPhase::Draw) {
                move_board_cursor(-1, 0);
                erase_glyph_at_cursor();
            }
            return true;

        case TuiAction::GlyphDelete:
            if (glyph_mode_.phase == GlyphPhase::Draw) {
                move_board_cursor(1, 0);
                erase_glyph_at_cursor();
            } else if (glyph_mode_.phase == GlyphPhase::Select) {
                erase_glyph_selection();
            } else {
                message_ = "Enter place, Esc cancel";
            }
            return true;

        case TuiAction::GlyphEscape:
            if (glyph_mode_.phase == GlyphPhase::Place) {
                cancel_glyph_placement();
            } else if (glyph_mode_.phase == GlyphPhase::Select) {
                toggle_glyph_selection();
            } else {
                leave_glyph_mode();
            }
            return true;

        case TuiAction::ConvertGlyphCard:
            convert_glyph_card();
            return true;

        case TuiAction::CopyGlyphs:
            copy_glyphs();
            return true;

        case TuiAction::CutGlyphs:
            cut_glyph_selection();
            return true;

        case TuiAction::PasteGlyphs:
            if (glyph_mode_.phase == GlyphPhase::Place) {
                message_ = "Enter place, Esc cancel";
            } else {
                paste_glyph_clipboard();
            }
            return true;

        case TuiAction::EdgeTab:
            if (edge_mode_.phase == EdgePhase::Browse) {
                cycle_edge_hit();
            } else if (edge_mode_.phase == EdgePhase::PickTarget) {
                toggle_manual_elbow();
            }
            return true;

        case TuiAction::EdgeEnter:
            finish_edge_action();
            return true;

        case TuiAction::EdgeDelete:
            erase_selected_edge();
            return true;

        case TuiAction::EdgeBackspace:
            remove_edge_waypoint();
            return true;

        case TuiAction::EdgeEscape:
            if (edge_mode_.phase == EdgePhase::Browse) {
                leave_edge_mode();
            } else {
                cancel_edge_draft();
            }
            return true;

        case TuiAction::EdgeBeginSource:
            if (edge_mode_.phase == EdgePhase::Browse) {
                begin_edge_source();
            }
            return true;

        case TuiAction::EdgeAutomatic:
            set_edge_build_mode(EdgeBuildMode::Automatic);
            return true;

        case TuiAction::EdgeManualOrEdit:
            if (edge_mode_.phase == EdgePhase::PickTarget) {
                set_edge_build_mode(EdgeBuildMode::Manual);
            } else {
                begin_manual_edge_edit();
            }
            return true;

        case TuiAction::EdgeReroute:
            reroute_selected_edge();
            return true;

        case TuiAction::EdgeLeave:
            leave_edge_mode();
            return true;

        default:
            return false;
    }
}

inline bool Tui::handle_active_event(const InputEvent& event) {
    const AppInputResult result = app_.handle_active_input(event);

    if (result.focus_requested) {
        locate_card(result.focus_card);
        return true;
    }

    if (result.handled) {
        message_.clear();
    }

    return result.handled;
}
