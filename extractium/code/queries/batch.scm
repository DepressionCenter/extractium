; Extraction rules for Windows batch files.
;
; A batch file has no functions. A label is where "call" and "goto" land,
; so each label is recorded as a function, named as the file writes it,
; colon included. The comment on the line after a label is its
; documentation, which is where batch authors put it; the comment block
; above is read when there is none below. Every command the file runs is
; recorded as a call, the way the PowerShell rules do it, because a
; batch file is a list of commands.
;
; This file is part of Extractium(TM)
; extractium/code/queries/batch.scm
; Copyright (C) 2026 The Regents of the University of Michigan
; Licensed under the GNU General Public License v3.0 or later.
; See README for full license information.

(program
  (label) @name @definition.function
  .
  (comment)? @doc)

(cmd
  (command_name) @call.name) @call
