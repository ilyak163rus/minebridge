rootProject.name = "minebridge-paper"

// Test-only plugin: separate artifact, never bundled in the production bridge.
include(":observer")
project(":observer").projectDir = file("../integration/observer-plugin")

