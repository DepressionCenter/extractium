; Extraction rules for shell scripts.
;
; A shell script has functions, the files it sources, and the commands it
; runs, and no classes or types at all -- which is why the registry entry
; for this language lists only the captures below.
;
; This file is part of Extractium(TM)
; extractium/code/queries/bash.scm
; Copyright (C) 2026 The Regents of the University of Michigan
; Licensed under the GNU General Public License v3.0 or later.
; See README for full license information.

(function_definition
  name: (word) @name) @definition.function

; "source lib.sh" and ". lib.sh" both read another script into this one.
((command
   name: (command_name) @_command
   argument: (_) @import.source) @import
 (#match? @_command "^(source|\\.)$"))

(command
  name: (command_name (word) @call.name)) @call
