-- A tiny page renderer, invented for the test suite.
local template = require("template")

local Page = {}

-- Renders one page from a title and a body.
function Page.render(title, body)
    return template.fill(title, body)
end

-- Reads a page's title, or returns a default.
local function title_of(page)
    return page.title or "Untitled"
end

function Page:describe()
    return title_of(self)
end

return Page
