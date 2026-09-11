# Builds the index on a Windows machine, invented for the test suite.
Import-Module Extractium

# Writes one line to the build log.
function Write-Step {
    param([string] $Message)
    Write-Output $Message
}

function Build-Index {
    param([string] $ConfigPath = "config.yaml")
    Write-Step "building"
    extractium build --config $ConfigPath
}

Build-Index
