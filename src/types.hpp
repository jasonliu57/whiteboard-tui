#pragma once

#include "spatial/geometry.hpp"

#include <functional>
#include <string>

using CardId         = u32;
using EdgeId         = u32;
using StaticFormatId = u32;
using LanguageId     = u32;

constexpr CardId kNoCard = ~CardId{0};
constexpr EdgeId kNoEdge = ~EdgeId{0};

enum class Key : u8 {
    Unknown,
    Text,
    Paste,
    Escape,
    Enter,
    Tab,
    Backspace,
    Delete,
    Left,
    Right,
    Up,
    Down,
    Home,
    End,
    PageUp,
    PageDown,
    CtrlA,
    CtrlB,
    CtrlC,
    CtrlD,
    CtrlE,
    CtrlG,
    CtrlQ,
    CtrlR,
    CtrlS,
    CtrlV,
    CtrlX,
    CtrlY,
    CtrlZ,
};

enum class MouseAction : u8 {
    None,
    LeftPress,
    LeftDrag,
    RightPress,
    MiddlePress,
    MiddleDrag,
    Release,
};

struct InputEvent {
    Key key = Key::Unknown;
    std::string text;
    bool shift = false;
    bool ctrl = false;
    MouseAction mouse = MouseAction::None;
    i32 mouse_x = 0;
    i32 mouse_y = 0;
};

struct PosHash {
    std::size_t operator()(Pos p) const noexcept {
        const std::size_t a = std::hash<i64>{}(p.x);
        const std::size_t b = std::hash<i64>{}(p.y);
        return a ^ (b + 0x9e3779b97f4a7c15ULL + (a << 6) + (a >> 2));
    }
};

struct Viewport {
    i64 x = 0;
    i64 y = 0;
    i32 width = 0;
    i32 height = 0;
};

enum TextAttribute : u8 {
    AttrNone      = 0,
    AttrBold      = 1 << 0,
    AttrUnderline = 1 << 1,
};

struct Style {
    u8 foreground = 7;
    u8 background = 0;
    u8 attributes = AttrNone;

    friend bool operator==(const Style&, const Style&) = default;
};

inline Style canonical_style(Style style) {
    if (style.foreground > 15) {
        style.foreground = 15;
    }

    if (style.background > 15) {
        style.background = 15;
    }

    style.attributes &= AttrBold | AttrUnderline;
    return style;
}

struct DisplayRune {
    char32_t glyph = U' ';
    i32 width = 1;
};
