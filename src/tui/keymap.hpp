#pragma once

#include "../types.hpp"

#include <cstddef>
#include <string_view>

enum class InputContext : u8 {
    ExportPrompt,
    ActiveCard,
    BoardCursor,
    BoardSelect,
    GlyphDraw,
    GlyphSelect,
    GlyphPlace,
    EdgeBrowse,
    EdgeBuild,
    EdgeEdit,
};

enum class TuiAction : u8 {
    None,

    AcceptProposal,
    RejectProposal,
    Save,
    ForceQuit,
    BeginFolderExport,
    Undo,
    Redo,
    RejectUndo,
    RejectRedo,

    CancelExport,
    CommitExport,
    ExportBackspace,
    LeaveActiveCard,

    MoveLeft,
    MoveRight,
    MoveUp,
    MoveDown,
    PanLeft,
    PanRight,
    PanUp,
    PanDown,
    SelectCornerLeft,
    SelectCornerRight,
    SelectCornerUp,
    SelectCornerDown,

    EnterSelection,
    LeaveSelection,
    BoardHome,
    BoardPageUp,
    BoardPageDown,
    EditCard,
    DeleteCard,
    CopyCard,
    CutCard,
    PasteCard,
    RejectTextPaste,
    ConvertTextArtGlyphs,
    MoveCardLeft,
    MoveCardRight,
    MoveCardUp,
    MoveCardDown,
    CreateNote,
    CreateMarkdown,
    CreateCode,
    CreateTodo,
    CreateCsv,
    CreateFolder,
    BeginEdge,
    BeginGlyph,
    QuitClean,

    GlyphTab,
    GlyphEnter,
    GlyphBackspace,
    GlyphDelete,
    GlyphEscape,
    ConvertGlyphCard,
    CopyGlyphs,
    CutGlyphs,
    PasteGlyphs,
    GlyphStepLeft,
    GlyphStepRight,
    GlyphStepUp,
    GlyphStepDown,

    EdgeTab,
    EdgeEnter,
    EdgeDelete,
    EdgeBackspace,
    EdgeEscape,
    EdgeBeginSource,
    EdgeAutomatic,
    EdgeManualOrEdit,
    EdgeReroute,
    EdgeLeave,
};

enum InputModifier : u8 {
    ModNone  = 0,
    ModShift = 1 << 0,
    ModCtrl  = 1 << 1,
};

struct Gesture {
    Key key = Key::Unknown;
    char32_t rune = U'\0';
    u8 modifiers = ModNone;
};

struct Binding {
    Gesture gesture;
    TuiAction action = TuiAction::None;
};

struct ContextBinding {
    u16 contexts = 0;
    Binding binding;
    std::string_view help;
};

static constexpr u16 context_bit(InputContext context) {
    return static_cast<u16>(
        u16{1} << static_cast<u8>(context)
    );
}

static constexpr u16 kBoardContexts =
    context_bit(InputContext::BoardCursor) |
    context_bit(InputContext::BoardSelect);
static constexpr u16 kGlyphContexts =
    context_bit(InputContext::GlyphDraw) |
    context_bit(InputContext::GlyphSelect) |
    context_bit(InputContext::GlyphPlace);
static constexpr u16 kEdgeContexts =
    context_bit(InputContext::EdgeBrowse) |
    context_bit(InputContext::EdgeBuild) |
    context_bit(InputContext::EdgeEdit);
static constexpr u16 kMoveContexts =
    kBoardContexts |
    kGlyphContexts |
    kEdgeContexts;
static constexpr u16 kPanContexts =
    kBoardContexts |
    context_bit(InputContext::GlyphDraw) |
    context_bit(InputContext::GlyphPlace) |
    kEdgeContexts;

static constexpr Binding key_binding(
    Key key,
    TuiAction action,
    u8 modifiers = ModNone
) {
    return {{key, U'\0', modifiers}, action};
}

static constexpr ContextBinding context_key(
    u16 contexts,
    Key key,
    TuiAction action,
    u8 modifiers = ModNone,
    std::string_view help = {}
) {
    return {
        contexts,
        key_binding(key, action, modifiers),
        help,
    };
}

static constexpr ContextBinding context_rune(
    u16 contexts,
    char32_t rune,
    TuiAction action
) {
    return {
        contexts,
        {{Key::Text, rune, ModNone}, action},
        {},
    };
}

static constexpr Binding kProposalBindings[] = {
    key_binding(Key::CtrlG, TuiAction::AcceptProposal),
    key_binding(Key::CtrlD, TuiAction::RejectProposal),
};

static constexpr Binding kGlobalBindings[] = {
    key_binding(Key::CtrlQ, TuiAction::ForceQuit),
    key_binding(Key::CtrlS, TuiAction::Save),
    key_binding(Key::CtrlE, TuiAction::BeginFolderExport),
    key_binding(Key::CtrlZ, TuiAction::Undo),
    key_binding(Key::CtrlY, TuiAction::Redo),
    key_binding(Key::CtrlR, TuiAction::Redo),
};

static constexpr std::size_t kProposalBindingCount =
    sizeof(kProposalBindings) / sizeof(kProposalBindings[0]);
static constexpr std::size_t kGlobalBindingCount =
    sizeof(kGlobalBindings) / sizeof(kGlobalBindings[0]);

static constexpr ContextBinding kContextBindings[] = {
    context_key(
        context_bit(InputContext::ExportPrompt),
        Key::Escape,
        TuiAction::CancelExport,
        ModNone,
        " | Enter write, Esc cancel"
    ),
    context_key(
        context_bit(InputContext::ExportPrompt),
        Key::Enter,
        TuiAction::CommitExport
    ),
    context_key(
        context_bit(InputContext::ExportPrompt),
        Key::Backspace,
        TuiAction::ExportBackspace
    ),
    context_key(
        context_bit(InputContext::ActiveCard),
        Key::Escape,
        TuiAction::LeaveActiveCard
    ),

    context_key(
        kGlyphContexts,
        Key::CtrlZ,
        TuiAction::RejectUndo
    ),
    context_key(
        kGlyphContexts,
        Key::CtrlY,
        TuiAction::RejectRedo
    ),
    context_key(
        kGlyphContexts,
        Key::CtrlR,
        TuiAction::RejectRedo
    ),

    context_key(kMoveContexts, Key::Left, TuiAction::MoveLeft),
    context_key(kMoveContexts, Key::Right, TuiAction::MoveRight),
    context_key(kMoveContexts, Key::Up, TuiAction::MoveUp),
    context_key(kMoveContexts, Key::Down, TuiAction::MoveDown),
    context_key(
        kPanContexts,
        Key::Left,
        TuiAction::PanLeft,
        ModShift
    ),
    context_key(
        kPanContexts,
        Key::Right,
        TuiAction::PanRight,
        ModShift
    ),
    context_key(
        kPanContexts,
        Key::Up,
        TuiAction::PanUp,
        ModShift
    ),
    context_key(
        kPanContexts,
        Key::Down,
        TuiAction::PanDown,
        ModShift
    ),
    context_key(
        context_bit(InputContext::GlyphSelect),
        Key::Left,
        TuiAction::SelectCornerLeft,
        ModShift
    ),
    context_key(
        context_bit(InputContext::GlyphSelect),
        Key::Right,
        TuiAction::SelectCornerRight,
        ModShift
    ),
    context_key(
        context_bit(InputContext::GlyphSelect),
        Key::Up,
        TuiAction::SelectCornerUp,
        ModShift
    ),
    context_key(
        context_bit(InputContext::GlyphSelect),
        Key::Down,
        TuiAction::SelectCornerDown,
        ModShift
    ),

    context_key(
        kBoardContexts,
        Key::Tab,
        TuiAction::EnterSelection
    ),
    context_key(
        kBoardContexts,
        Key::Tab,
        TuiAction::EnterSelection,
        ModShift
    ),
    context_key(
        context_bit(InputContext::BoardSelect),
        Key::Escape,
        TuiAction::LeaveSelection
    ),
    context_key(
        context_bit(InputContext::BoardCursor),
        Key::Home,
        TuiAction::BoardHome
    ),
    context_key(
        context_bit(InputContext::BoardCursor),
        Key::PageUp,
        TuiAction::BoardPageUp
    ),
    context_key(
        context_bit(InputContext::BoardCursor),
        Key::PageDown,
        TuiAction::BoardPageDown
    ),
    context_key(kBoardContexts, Key::Enter, TuiAction::EditCard),
    context_key(kBoardContexts, Key::Delete, TuiAction::DeleteCard),
    context_key(kBoardContexts, Key::CtrlC, TuiAction::CopyCard),
    context_key(kBoardContexts, Key::CtrlX, TuiAction::CutCard),
    context_key(kBoardContexts, Key::CtrlV, TuiAction::PasteCard),
    context_key(
        kBoardContexts,
        Key::Paste,
        TuiAction::RejectTextPaste
    ),
    context_rune(
        context_bit(InputContext::BoardSelect),
        U'c',
        TuiAction::ConvertTextArtGlyphs
    ),

    context_rune(kBoardContexts, U'h', TuiAction::MoveLeft),
    context_rune(kBoardContexts, U'l', TuiAction::MoveRight),
    context_rune(kBoardContexts, U'k', TuiAction::MoveUp),
    context_rune(kBoardContexts, U'j', TuiAction::MoveDown),
    context_rune(kBoardContexts, U'H', TuiAction::MoveCardLeft),
    context_rune(kBoardContexts, U'L', TuiAction::MoveCardRight),
    context_rune(kBoardContexts, U'K', TuiAction::MoveCardUp),
    context_rune(kBoardContexts, U'J', TuiAction::MoveCardDown),
    context_rune(kBoardContexts, U'n', TuiAction::CreateNote),
    context_rune(kBoardContexts, U'm', TuiAction::CreateMarkdown),
    context_rune(kBoardContexts, U'c', TuiAction::CreateCode),
    context_rune(kBoardContexts, U't', TuiAction::CreateTodo),
    context_rune(kBoardContexts, U'v', TuiAction::CreateCsv),
    context_rune(kBoardContexts, U'f', TuiAction::CreateFolder),
    context_rune(kBoardContexts, U'g', TuiAction::BeginEdge),
    context_rune(kBoardContexts, U'i', TuiAction::BeginGlyph),
    context_rune(kBoardContexts, U'e', TuiAction::EditCard),
    context_rune(kBoardContexts, U'x', TuiAction::DeleteCard),
    context_rune(kBoardContexts, U'y', TuiAction::CopyCard),
    context_rune(kBoardContexts, U'd', TuiAction::CutCard),
    context_rune(kBoardContexts, U'p', TuiAction::PasteCard),
    context_rune(kBoardContexts, U'u', TuiAction::Undo),
    context_rune(kBoardContexts, U'q', TuiAction::QuitClean),
    context_rune(kBoardContexts, U'Q', TuiAction::ForceQuit),

    context_key(
        context_bit(InputContext::GlyphDraw),
        Key::Tab,
        TuiAction::GlyphTab,
        ModNone,
        " | type Unicode, Ctrl-C copy, Ctrl-V paste, Tab select"
    ),
    context_key(
        context_bit(InputContext::GlyphSelect),
        Key::Tab,
        TuiAction::GlyphTab,
        ModNone,
        " | arrows frame, Shift-arrows corner, HJKL place,"
        " c card, Ctrl-C/X, Del erase"
    ),
    context_key(
        context_bit(InputContext::GlyphPlace),
        Key::Tab,
        TuiAction::GlyphTab,
        ModNone,
        " | arrows/HJKL move, Enter overwrite, Esc cancel"
    ),
    context_key(kGlyphContexts, Key::Tab, TuiAction::GlyphTab, ModShift),
    context_key(kGlyphContexts, Key::Enter, TuiAction::GlyphEnter),
    context_key(
        kGlyphContexts,
        Key::Backspace,
        TuiAction::GlyphBackspace
    ),
    context_key(kGlyphContexts, Key::Delete, TuiAction::GlyphDelete),
    context_key(kGlyphContexts, Key::Escape, TuiAction::GlyphEscape),
    context_rune(
        context_bit(InputContext::GlyphSelect),
        U'c',
        TuiAction::ConvertGlyphCard
    ),
    context_key(kGlyphContexts, Key::CtrlC, TuiAction::CopyGlyphs),
    context_key(kGlyphContexts, Key::CtrlX, TuiAction::CutGlyphs),
    context_key(kGlyphContexts, Key::CtrlV, TuiAction::PasteGlyphs),
    context_rune(
        context_bit(InputContext::GlyphSelect) |
            context_bit(InputContext::GlyphPlace),
        U'H',
        TuiAction::GlyphStepLeft
    ),
    context_rune(
        context_bit(InputContext::GlyphSelect) |
            context_bit(InputContext::GlyphPlace),
        U'L',
        TuiAction::GlyphStepRight
    ),
    context_rune(
        context_bit(InputContext::GlyphSelect) |
            context_bit(InputContext::GlyphPlace),
        U'K',
        TuiAction::GlyphStepUp
    ),
    context_rune(
        context_bit(InputContext::GlyphSelect) |
            context_bit(InputContext::GlyphPlace),
        U'J',
        TuiAction::GlyphStepDown
    ),

    context_key(
        context_bit(InputContext::EdgeBrowse),
        Key::Tab,
        TuiAction::EdgeTab,
        ModNone,
        " | Enter source/edit, Tab cycle, r route"
    ),
    context_key(
        context_bit(InputContext::EdgeBuild) |
            context_bit(InputContext::EdgeEdit),
        Key::Tab,
        TuiAction::EdgeTab
    ),
    context_key(kEdgeContexts, Key::Tab, TuiAction::EdgeTab, ModShift),
    context_key(kEdgeContexts, Key::Enter, TuiAction::EdgeEnter),
    context_key(kEdgeContexts, Key::Delete, TuiAction::EdgeDelete),
    context_key(
        kEdgeContexts,
        Key::Backspace,
        TuiAction::EdgeBackspace
    ),
    context_key(kEdgeContexts, Key::Escape, TuiAction::EdgeEscape),
    context_rune(kEdgeContexts, U'h', TuiAction::MoveLeft),
    context_rune(kEdgeContexts, U'l', TuiAction::MoveRight),
    context_rune(kEdgeContexts, U'k', TuiAction::MoveUp),
    context_rune(kEdgeContexts, U'j', TuiAction::MoveDown),
    context_rune(
        kEdgeContexts,
        U'n',
        TuiAction::EdgeBeginSource
    ),
    context_rune(
        kEdgeContexts,
        U'a',
        TuiAction::EdgeAutomatic
    ),
    context_rune(
        kEdgeContexts,
        U'm',
        TuiAction::EdgeManualOrEdit
    ),
    context_rune(kEdgeContexts, U'r', TuiAction::EdgeReroute),
    context_rune(kEdgeContexts, U'x', TuiAction::EdgeDelete),
    context_rune(kEdgeContexts, U'q', TuiAction::EdgeLeave),
};

static u8 event_modifiers(const InputEvent& event) {
    return
        (event.shift ? ModShift : ModNone) |
        (event.ctrl ? ModCtrl : ModNone);
}

static bool binding_matches(
    const Binding& binding,
    const InputEvent& event,
    char32_t rune = U'\0'
) {
    return
        binding.gesture.key == event.key &&
        binding.gesture.rune == rune &&
        binding.gesture.modifiers == event_modifiers(event);
}

static const Binding* resolve_binding(
    const Binding* bindings,
    std::size_t count,
    const InputEvent& event
) {
    for (std::size_t i = 0; i < count; ++i) {
        if (binding_matches(bindings[i], event)) {
            return &bindings[i];
        }
    }

    return nullptr;
}

static const Binding* resolve_context_binding(
    InputContext context,
    const InputEvent& event,
    char32_t rune = U'\0'
) {
    const u16 bit = context_bit(context);

    for (const ContextBinding& binding : kContextBindings) {
        if (
            (binding.contexts & bit) != 0 &&
            binding_matches(binding.binding, event, rune)
        ) {
            return &binding.binding;
        }
    }

    return nullptr;
}

static std::string_view input_context_help(InputContext context) {
    const u16 bit = context_bit(context);

    for (const ContextBinding& binding : kContextBindings) {
        if (
            (binding.contexts & bit) != 0 &&
            !binding.help.empty()
        ) {
            return binding.help;
        }
    }

    return {};
}

static bool action_direction(
    TuiAction action,
    i64& dx,
    i64& dy
) {
    dx = 0;
    dy = 0;

    switch (action) {
        case TuiAction::MoveLeft:
        case TuiAction::PanLeft:
        case TuiAction::SelectCornerLeft:
        case TuiAction::MoveCardLeft:
        case TuiAction::GlyphStepLeft:
            dx = -1;
            return true;

        case TuiAction::MoveRight:
        case TuiAction::PanRight:
        case TuiAction::SelectCornerRight:
        case TuiAction::MoveCardRight:
        case TuiAction::GlyphStepRight:
            dx = 1;
            return true;

        case TuiAction::MoveUp:
        case TuiAction::PanUp:
        case TuiAction::SelectCornerUp:
        case TuiAction::MoveCardUp:
        case TuiAction::GlyphStepUp:
            dy = -1;
            return true;

        case TuiAction::MoveDown:
        case TuiAction::PanDown:
        case TuiAction::SelectCornerDown:
        case TuiAction::MoveCardDown:
        case TuiAction::GlyphStepDown:
            dy = 1;
            return true;

        default:
            return false;
    }
}

static bool move_action(TuiAction action) {
    return
        action >= TuiAction::MoveLeft &&
        action <= TuiAction::MoveDown;
}

static bool pan_action(TuiAction action) {
    return
        action >= TuiAction::PanLeft &&
        action <= TuiAction::PanDown;
}

static bool corner_action(TuiAction action) {
    return
        action >= TuiAction::SelectCornerLeft &&
        action <= TuiAction::SelectCornerDown;
}

static bool move_card_action(TuiAction action) {
    return
        action >= TuiAction::MoveCardLeft &&
        action <= TuiAction::MoveCardDown;
}

static bool glyph_step_action(TuiAction action) {
    return
        action >= TuiAction::GlyphStepLeft &&
        action <= TuiAction::GlyphStepDown;
}
