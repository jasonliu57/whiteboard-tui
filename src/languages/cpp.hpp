#pragma once

#include "ids.hpp"

#include <tree-sitter-cpp.h>

#include <string_view>

constexpr std::string_view kCppHighlights = R"query(
[
  "alignas"
  "alignof"
  "break"
  "case"
  "class"
  "concept"
  "const"
  "constexpr"
  "continue"
  "default"
  "delete"
  "do"
  "else"
  "enum"
  "for"
  "if"
  "namespace"
  "new"
  "private"
  "protected"
  "public"
  "requires"
  "return"
  "sizeof"
  "static"
  "struct"
  "switch"
  "template"
  "throw"
  "try"
  "typedef"
  "typename"
  "union"
  "using"
  "virtual"
  "while"
] @keyword

[
  (primitive_type)
  (type_identifier)
  (namespace_identifier)
] @type

(function_declarator
  declarator: (identifier) @function)

(call_expression
  function: (identifier) @function)

[
  (string_literal)
  (raw_string_literal)
  (char_literal)
  (system_lib_string)
] @string

(number_literal) @number
(comment) @comment

[
  (true)
  (false)
  (null)
] @constant

[
  (preproc_include)
  (preproc_def)
  (preproc_function_def)
] @preprocessor
)query";

static Style cpp_highlight_style(std::string_view capture) {
    if (capture == "keyword") {
        return {5, 0, AttrBold};
    }

    if (capture == "type") {
        return {6, 0, AttrNone};
    }

    if (capture == "function") {
        return {4, 0, AttrNone};
    }

    if (capture == "string") {
        return {2, 0, AttrNone};
    }

    if (capture == "comment") {
        return {6, 0, AttrNone};
    }

    if (capture == "preprocessor") {
        return {3, 0, AttrBold};
    }

    return {3, 0, AttrNone};
}
