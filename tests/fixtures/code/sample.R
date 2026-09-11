# Summarizes enrollment by wave. Invented for the test suite.
library(dplyr)

# Counts the participants enrolled in one wave.
wave_size <- function(enrollments, wave) {
  nrow(dplyr::filter(enrollments, wave_id == wave))
}

# Returns the waves with no enrollments yet.
empty_waves <- function(enrollments, waves) {
  setdiff(waves, unique(enrollments$wave_id))
}
