; Extraction rules for C#.
;
; This file is part of Extractium(TM)
; extractium/code/queries/csharp.scm
; Copyright (C) 2026 The Regents of the University of Michigan
; Licensed under the GNU General Public License v3.0 or later.
; See README for full license information.

(class_declaration
  name: (identifier) @name) @definition.class

(record_declaration
  name: (identifier) @name) @definition.class

(struct_declaration
  name: (identifier) @name) @definition.type

(interface_declaration
  name: (identifier) @name) @definition.type

(enum_declaration
  name: (identifier) @name) @definition.type

(namespace_declaration
  name: (_) @name) @definition.module

(method_declaration
  name: (identifier) @name) @definition.method

(constructor_declaration
  name: (identifier) @name) @definition.method

(property_declaration
  name: (identifier) @name) @definition.method

(delegate_declaration
  name: (identifier) @name) @definition.type

(using_directive
  (_) @import.source) @import

(invocation_expression
  function: [(identifier) @call.name
             (member_access_expression name: (identifier) @call.name)]) @call
