import json
import os
import subprocess
import sys

# Mapping from Root Folders to Fabric Targets / Workspaces
FOLDER_TO_TARGET = {
    "DataOps": "sales",
    "ws-finance": "finance",
    "ws-deploy-poc": "operations",
}


def get_git_diff_files():
    """Retrieves the list of modified files using Git Diff."""
    base_sha = os.getenv("GITHUB_BASE_SHA")
    head_sha = os.getenv("GITHUB_HEAD_SHA")

    # 1. Execution in Pull Request / CI/CD environment with explicit SHAs
    if base_sha and head_sha:
        cmd = ["git", "diff", "--name-only", base_sha, head_sha]
        print(f"🚀 CI/CD Mode: Comparing PR commit range ({base_sha[:7]}...{head_sha[:7]})")
    else:
        # 2. Local Git execution or fallback to base branch
        base_ref = os.getenv("GITHUB_BASE_REF", "main")
        target_branch = f"origin/{base_ref}"
        cmd = ["git", "diff", "--name-only", f"{target_branch}...HEAD"]
        print(f"🚀 Git Mode: Comparing HEAD against target branch ({target_branch})")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.splitlines()
    except subprocess.CalledProcessError as e:
        print(f"❌ Error executing git diff: {e.stderr}")
        sys.exit(1)


def analyze_repository_changes():
    """Analyzes modified files and builds refresh payloads grouped by Target."""
    changed_files = get_git_diff_files()

    tables_by_target = {}
    external_tmdl_by_target = {}
    detected_targets = set()

    for file_path in changed_files:
        file_path = file_path.strip()
        if not file_path:
            continue

        normalized_path = file_path.replace("\\", "/")
        parts = normalized_path.split("/")

        # 1. Identify Target/Workspace based on the root folder
        root_folder = parts[0]
        target = FOLDER_TO_TARGET.get(root_folder)

        if not target:
            continue  # The file does not belong to a monitored workspace folder

        detected_targets.add(target)

        # Initialize collections for the target
        if target not in tables_by_target:
            tables_by_target[target] = {}
        if target not in external_tmdl_by_target:
            external_tmdl_by_target[target] = set()

        # 2. Analyze if the file modification corresponds to a Semantic Model
        if ".SemanticModel/definition/" in normalized_path:
            model_folder = next(
                (p for p in parts if p.endswith(".SemanticModel")), None
            )
            model_name = (
                model_folder.replace(".SemanticModel", "")
                if model_folder
                else "UnknownModel"
            )

            # CASE A: Modification inside the 'tables' directory
            if "/definition/tables/" in normalized_path:
                tables_index = parts.index("tables")
                if len(parts) > tables_index + 1:
                    table_file = parts[tables_index + 1]
                    table_name = os.path.splitext(table_file)[0]

                    if model_name not in tables_by_target[target]:
                        tables_by_target[target][model_name] = set()
                    tables_by_target[target][model_name].add(table_name)

            # CASE B: Modification in root .tmdl files (model.tmdl, relationships.tmdl, etc.)
            elif normalized_path.endswith(".tmdl"):
                external_tmdl_by_target[target].add(model_name)

    # 3. Build the final JSON payloads grouped by Target
    payloads_by_target = {}

    for target in detected_targets:
        payloads_by_target[target] = {}

        # Map partial refreshes by table and partition
        if target in tables_by_target:
            for model_name, tables in tables_by_target[target].items():
                payloads_by_target[target][model_name] = {
                    "refresh_mode": "partial_tables",
                    "api_payload": {
                        "type": "full",
                        "commitMode": "transactional",
                        "objects": [
                            {"table": t, "partition": t}
                            for t in sorted(list(tables))
                        ],
                    },
                }

        # Map full model refreshes
        if target in external_tmdl_by_target:
            for model_name in external_tmdl_by_target[target]:
                if model_name not in payloads_by_target[target]:
                    payloads_by_target[target][model_name] = {
                        "refresh_mode": "full_model",
                        "api_payload": {
                            "type": "full",
                            "commitMode": "transactional",
                        },
                    }

    return detected_targets, payloads_by_target


def print_summary(targets, payloads):
    """Prints a clean human-readable summary for pipeline logs."""
    print("\n==============================================")
    print(f"🎯 DETECTED TARGETS: {', '.join(sorted(targets)) if targets else 'None'}")
    print("==============================================")

    for target in sorted(targets):
        models = payloads.get(target, {})
        print(f"\n📂 Target Workspace: [{target.upper()}]")

        if not models:
            print("   ℹ️  Folder changes detected, but no Semantic Model definitions were modified.")
            continue

        for model_name, data in models.items():
            mode = data["refresh_mode"]
            if mode == "partial_tables":
                tables = [obj["table"] for obj in data["api_payload"]["objects"]]
                print(f"   📌 Model: {model_name} [Mode: Partial Refresh]")
                for t in tables:
                    print(f"      • Table: {t}")
            elif mode == "full_model":
                print(f"   📌 Model: {model_name} [Mode: Full Model Refresh]")
                print("      • Root TMDL files modified")


if __name__ == "__main__":
    targets, payloads = analyze_repository_changes()

    # 1. Print console summary
    print_summary(targets, payloads)

    targets_str = " ".join(sorted(list(targets)))
    payloads_json_str = json.dumps(payloads)
    has_changes_str = str(len(targets) > 0).lower()

    # 2. Export to GITHUB_OUTPUT (for GitHub Actions step parameters)
    github_output = os.getenv("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            f.write(f"has_changes={has_changes_str}\n")
            f.write(f"targets={targets_str}\n")
            f.write(f"refresh_payloads={payloads_json_str}\n")

    # 3. Export to GITHUB_ENV (maintains backwards compatibility with existing .py scripts)
    github_env = os.getenv("GITHUB_ENV")
    if github_env:
        with open(github_env, "a", encoding="utf-8") as f:
            f.write(f"TARGETS={targets_str}\n")
            if not targets:
                f.write("SKIP_PIPELINE=true\n")