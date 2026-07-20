#include "../board_document.hpp"

BoardDocument::BoardDocument() = default;

bool BoardDocument::dirty() const noexcept {
    return untracked_dirty || history.dirty();
}
