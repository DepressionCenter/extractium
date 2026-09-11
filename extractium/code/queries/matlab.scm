; Extraction rules for MATLAB.
;
; MATLAB writes a function's documentation as the comment block directly
; under its signature rather than above it -- the text "help" prints --
; so that comment is captured here rather than left to the engine's rule
; for comments above a definition.
;
; This file is part of Extractium(TM)
; extractium/code/queries/matlab.scm
; Copyright (C) 2026 The Regents of the University of Michigan
; Licensed under the GNU General Public License v3.0 or later.
; See README for full license information.

(function_definition
  name: (identifier) @name
  (comment)? @doc) @definition.function

(class_definition
  name: (identifier) @name) @definition.class

(function_call
  name: (identifier) @call.name) @call
