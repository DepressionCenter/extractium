; Extraction rules for SQL.
;
; A registry pull, a cohort definition, and a REDCap export are all
; written in SQL, and what a reader looks for in one is the table, view,
; or routine it defines. SQL has no imports and no calls between files,
; so this file captures neither: an empty answer is better than an
; invented one.
;
; This file is part of Extractium(TM)
; extractium/code/queries/sql.scm
; Copyright (C) 2026 The Regents of the University of Michigan
; Licensed under the GNU General Public License v3.0 or later.
; See README for full license information.

(create_table
  (object_reference name: (identifier) @name)) @definition.type

(create_view
  (object_reference name: (identifier) @name)) @definition.type

(create_materialized_view
  (object_reference name: (identifier) @name)) @definition.type

(create_function
  (object_reference name: (identifier) @name)) @definition.function
