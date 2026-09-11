--- Participants active in the current wave ---
-- Grain: one row per participant per wave.
-- Invented for the test suite; no real study is described here.

CREATE VIEW active_participants AS
SELECT
    p.participant_id,
    p.enrollment_date,
    w.wave_number
FROM participants AS p
INNER JOIN waves AS w
    ON w.wave_id = p.wave_id
WHERE p.status = 'active'
;

-- Counts the participants enrolled in one wave.
CREATE FUNCTION wave_size(wave integer) RETURNS integer AS $$
    SELECT count(*) FROM participants WHERE wave_id = wave;
$$ LANGUAGE SQL;
