; Extraction rules for Rust.
;
; This file is part of Extractium(TM)
; extractium/code/queries/rust.scm
; Copyright (C) 2026 The Regents of the University of Michigan
; Licensed under the GNU General Public License v3.0 or later.
; See README for full license information.

(mod_item
  name: (identifier) @name) @definition.module

(function_item
  name: (identifier) @name) @definition.function

; A method a trait declares without a body.
(function_signature_item
  name: (identifier) @name) @definition.function

; A struct is the nearest thing Rust has to a class, and an impl block
; is where its methods live. The block is recorded as a class named for
; the type it implements, so each method inside it is attributed to
; that type rather than read as a loose function.
(struct_item
  name: (type_identifier) @name) @definition.class

(impl_item
  type: (_) @name) @definition.class

(enum_item
  name: (type_identifier) @name) @definition.type

(union_item
  name: (type_identifier) @name) @definition.type

(trait_item
  name: (type_identifier) @name) @definition.type

(type_item
  name: (type_identifier) @name) @definition.type

(const_item
  name: (identifier) @name) @definition.constant

(static_item
  name: (identifier) @name) @definition.constant

(use_declaration
  argument: (_) @import.source) @import

(call_expression
  function: [(identifier) @call.name
             (scoped_identifier name: (identifier) @call.name)
             (field_expression field: (field_identifier) @call.name)]) @call

; A macro call is a call to a reader: println!, vec!, and the like.
(macro_invocation
  macro: (identifier) @call.name) @call
