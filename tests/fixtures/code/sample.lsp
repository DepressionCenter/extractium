<html>
<head><title>Study calendar</title></head>
<body>
<h1>Study calendar</h1>
<p>Lists the visits booked this week. Invented for the test suite.</p>
<?lua
-- Returns the visits booked in one week.
local function visits_this_week(calendar)
  return calendar.week()
end

for _, visit in ipairs(visits_this_week(calendar)) do
?>
<div class="visit"><%= visit.label %></div>
<?lua end ?>
</body>
</html>
