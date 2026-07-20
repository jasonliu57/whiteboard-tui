#pragma once

#include "../platform/native/app_io.hpp"

#include "native.hpp"

inline void NativeTui::append_export_parent(std::string_view text) {
    for (u32 byte = 0; byte < text.size();) {
        const Rune rune = decode_utf8(text, byte);

        if (rune.codepoint == U'\n' || rune.codepoint == U'\r') {
            break;
        }

        if (
            rune.codepoint >= 0x20 &&
            !(rune.codepoint >= 0x7F && rune.codepoint < 0xA0)
        ) {
            export_parent_.append(text.substr(byte, rune.bytes));
        }

        byte += rune.bytes;
    }
}

inline void NativeTui::begin_folder_export() {
    const CardId id = app_.session.active != kNoCard
        ? app_.session.active
        : require_target_card();

    if (id == kNoCard) {
        return;
    }

    if (!app_.is_folder(id)) {
        message_ = "not a folder";
        return;
    }

    exporting_folder_ = id;
    export_parent_.clear();
    message_.clear();
}

inline void NativeTui::finish_folder_export() {
    const std::string_view parent = export_parent_.empty()
        ? std::string_view{"."}
        : std::string_view{export_parent_};
    const FolderExportResult result = whiteboard::native::export_folder(app_,
        exporting_folder_,
        parent
    );

    exporting_folder_ = kNoCard;
    export_parent_.clear();

    if (result.ok()) {
        message_ = "exported ";
        append_decimal(message_, result.files_written);
        message_.append(" files:");
        message_.append(result.path);
        return;
    }

    switch (result.error) {
        case FolderExportError::InvalidPlan:
            switch (result.issue) {
                case FolderExportIssueKind::InvalidName:
                    message_ = "export invalid name:";
                    break;
                case FolderExportIssueKind::MissingCard:
                    message_ = "export missing card:";
                    append_decimal(message_, result.card);
                    message_.append(" path:");
                    break;
                case FolderExportIssueKind::DuplicatePath:
                    message_ = "export duplicate path:";
                    break;
                case FolderExportIssueKind::UnsupportedFormat:
                    message_ = "export unsupported card:";
                    append_decimal(message_, result.card);
                    message_.append(" path:");
                    break;
            }
            break;

        case FolderExportError::RootExists:
            message_ = "export root exists:";
            break;
        case FolderExportError::CreateDirectory:
            message_ = "export mkdir failed:";
            break;
        case FolderExportError::OpenFile:
            message_ = "export open failed:";
            break;
        case FolderExportError::WriteFile:
            message_ = "export write failed:";
            break;
        case FolderExportError::None:
            break;
    }

    message_.append(result.path);

    if (result.system_error != 0) {
        message_.append(" errno:");
        append_decimal(message_, result.system_error);
    }

    if (result.files_written != 0) {
        message_.append(" after:");
        append_decimal(message_, result.files_written);
    }
}

inline void NativeTui::save() {
    message_ = whiteboard::native::save(app_, main_file_)
        ? "saved"
        : app_.file_error;
}

inline bool NativeTui::native_command(TuiAction action) {
    switch (action) {
        case TuiAction::AcceptProposal:
            accept_agent_proposal();
            return true;

        case TuiAction::RejectProposal:
            reject_agent_proposal();
            return true;

        case TuiAction::Save:
            save();
            return true;

        case TuiAction::ForceQuit:
            running_ = false;
            return false;

        case TuiAction::BeginFolderExport:
            begin_folder_export();
            return true;

        case TuiAction::CancelExport:
            exporting_folder_ = kNoCard;
            export_parent_.clear();
            message_ = "export canceled";
            return true;

        case TuiAction::CommitExport:
            finish_folder_export();
            return true;

        case TuiAction::ExportBackspace:
            if (!export_parent_.empty()) {
                export_parent_.erase(previous_utf8_byte(
                    export_parent_,
                    static_cast<u32>(export_parent_.size())
                ));
            }
            return true;

        case TuiAction::QuitClean:
            if (app_.dirty()) {
                message_ = "unsaved: Ctrl-S or Q to force quit";
            } else {
                running_ = false;
            }
            return true;

        default: return false;
    }
}

inline bool NativeTui::native_input(InputEvent& event) {
    if (exporting_folder_ != kNoCard) {
        if (event.key == Key::Text || event.key == Key::Paste) {
            append_export_parent(event.text);
            return true;
        }

        const Binding* binding = resolve_context_binding(
            InputContext::ExportPrompt,
            event
        );
        if (binding) native_command(binding->action);
        return true;
    }

    if (pending_agent_proposal_.has_value()) {
        const Binding* binding = resolve_binding(
            kProposalBindings,
            kProposalBindingCount,
            event
        );

        if (binding != nullptr) {
            return native_command(binding->action);
        }
    }

    return false;
}

inline void NativeTui::native_status(std::string& result) {
    if (exporting_folder_ != kNoCard) {
        result = " EXPORT parent[.]:";
        result.append(export_parent_);
        result.append(input_context_help(
            InputContext::ExportPrompt
        ));
        return;
    }

    if (pending_agent_proposal_.has_value()) {
        result.append(" | AGENT proposal:");
        append_decimal(result, pending_agent_proposal_->id);
        result.append(" Ctrl-G accept Ctrl-D reject");
    }

}
