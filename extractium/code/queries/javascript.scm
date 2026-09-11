; Extraction rules for JavaScript.
;
; Adapted from the tag queries the tree-sitter-javascript grammar
; publishes, which are licensed under the MIT License, copyright (c) 2017
; Max Brunsfeld. The capture names differ: this file uses the set
; extractium/code/languages.py defines, so one engine reads every
; language the same way.
;
; This file is part of Extractium(TM)
; extractium/code/queries/javascript.scm
; Copyright (C) 2026 The Regents of the University of Michigan
; Licensed under the GNU General Public License v3.0 or later.
; See README for full license information.

(class_declaration
  name: (identifier) @name) @definition.class

(function_declaration
  name: (identifier) @name) @definition.function

(generator_function_declaration
  name: (identifier) @name) @definition.function

(method_definition
  name: (property_identifier) @name) @definition.method

; A function given a name by being assigned to one, which is how most
; modern JavaScript declares one.
(variable_declarator
  name: (identifier) @name
  value: [(arrow_function) (function_expression)]) @definition.function

(import_statement
  source: (string) @import.source) @import

; require("..."), which is how a file written for Node brings another in.
((variable_declarator
   value: (call_expression
     function: (identifier) @_require
     arguments: (arguments (string) @import.source))) @import
 (#eq? @_require "require"))

(call_expression
  function: [(identifier) @call.name
             (member_expression property: (property_identifier) @call.name)]) @call
