; Extraction rules for PowerShell.
;
; PowerShell runs a command and calls a function with the same syntax, so
; every command a script runs is recorded as a call. Import-Module is
; recorded as an import as well, because that is what it is.
;
; This file is part of Extractium(TM)
; extractium/code/queries/powershell.scm
; Copyright (C) 2026 The Regents of the University of Michigan
; Licensed under the GNU General Public License v3.0 or later.
; See README for full license information.

(function_statement
  (function_name) @name) @definition.function

(class_statement
  (simple_name) @name) @definition.class

((command
   command_name: (command_name) @_command
   command_elements: (command_elements (generic_token) @import.source)) @import
 (#match? @_command "^([Ii]mport-[Mm]odule|[Uu]sing)$"))

(command
  command_name: (command_name) @call.name) @call
