% Summarizes an actigraphy recording, invented for the test suite.
% No real participant data is described here.

function summary = summarize_recording(counts, sampling_hz)
% Returns the mean and the peak of one recording.
    summary.mean = mean(counts);
    summary.peak = max(counts);
    summary.minutes = numel(counts) / (sampling_hz * 60);
end

% Drops the samples recorded while the device was off the wrist.
function kept = drop_offwrist(counts, worn)
    kept = counts(worn);
end
