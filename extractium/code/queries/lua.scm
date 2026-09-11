; Extraction rules for Lua.
;
; Lua writes a method as a function whose name carries its table, so
; "Page.render" and "Page:describe" are recorded under those names rather
; than reduced to "render" and "describe", which would lose the half a
; reader searches by.
;
; This file is part of Extractium(TM)
; extractium/code/queries/lua.scm
; Copyright (C) 2026 The Regents of the University of Michigan
; Licensed under the GNU General Public License v3.0 or later.
; See README for full license information.

(function_declaration
  name: (identifier) @name) @definition.function

(function_declaration
  name: (dot_index_expression) @name) @definition.function

(function_declaration
  name: (method_index_expression) @name) @definition.method

; require("module"), which is how Lua brings another file in.
((function_call
   name: (identifier) @_require
   arguments: (arguments (string) @import.source)) @import
 (#eq? @_require "require"))

(function_call
  name: [(identifier) @call.name
         (dot_index_expression field: (identifier) @call.name)
         (method_index_expression method: (identifier) @call.name)]) @call
