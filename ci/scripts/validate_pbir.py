import json
import sys
from pathlib import Path

violations = []

print("Searching for PBIR files...")

for pbir in Path(".").rglob("definition.pbir"):

    try:
        with open(pbir, "r", encoding="utf-8") as f:
            data = json.load(f)

        connection_string = (
            data.get("datasetReference", {})
                .get("byConnection", {})
                .get("connectionString", "")
        )

        if "/fw-" in connection_string.lower():

            violations.append({
                "file": str(pbir),
                "connection": connection_string
            })

    except Exception as ex:

        print(f"Unable to read {pbir}")
        print(ex)

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

    sys.exit(1)

print("✅ Validation passed.")