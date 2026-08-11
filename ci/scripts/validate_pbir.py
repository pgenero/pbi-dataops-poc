import json
import sys
from pathlib import Path

# List to collect any PBIR files violating the cross-workspace live connection rule
violations = []

print("Searching for PBIR files...")

# Recursively search the entire repository workspace (checked out branch) 
# for any Power BI report definition file named 'definition.pbir'
for pbir in Path(".").rglob("definition.pbir"):

    try:
        # Read and parse the PBIR JSON structure
        with open(pbir, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Extract the connection string from datasetReference -> byConnection -> connectionString
        connection_string = (
            data.get("datasetReference", {})
                .get("byConnection", {})
                .get("connectionString", "")
        )

        # Check if the connection string references a Feature Workspace (identifiable by '/fw-')
        if "/fw-" in connection_string.lower():

            violations.append({
                "file": str(pbir),
                "connection": connection_string
            })

    except Exception as ex:

        print(f"Unable to read {pbir}")
        print(ex)

# If any violations were detected, print details and block the pipeline
if violations:

    print("\n")
    print("======================================")
    print("❌ FEATURE WORKSPACE DETECTED")
    print("======================================")
    print("\n")

    for violation in violations:

        print(f"File: {violation['file']}")
        print(f"Connection: {violation['connection']}")
        print()

    # Exit with code 1 to fail the GitHub Action quality gate and block PR merge
    sys.exit(1)

print("✅ Validation passed.")