import json
import os
import subprocess
import sys
from pathlib import Path

# Path to the JSON configuration mapping Git Repository root folders to Fabric targets
CONFIG_PATH = Path("ci/config/folder_target_mapping.json")


def load_folder_target_mapping() -> dict:
    """Loads the folder-to-target mapping dictionary from a JSON configuration file.
    
    Returns:
        dict: Mapping between Git Repository root folder names and Fabric target identifiers.
    """
    if not CONFIG_PATH.exists():
        print(f"❌ Configuration file not found at: {CONFIG_PATH}")
        sys.exit(1)

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            mapping = json.load(f)
            print(f"⚙️ Loaded folder-to-target mapping from {CONFIG_PATH}")
            return mapping
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON format in {CONFIG_PATH}: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unable to read configuration file {CONFIG_PATH}: {e}")
        sys.exit(1)


def get_git_diff_file_statuses() -> list:
    """Retrieves the list of modified files with their Git status (Added, Modified, Deleted).
    
    Returns:
        list: Tuples containing (status_code, file_path).
    """
    base_sha = os.getenv("GITHUB_BASE_SHA")
    head_sha = os.getenv("GITHUB_HEAD_SHA")

    # 1. Execution in Pull Request / CI/CD environment with explicit commit SHAs
    if base_sha and head_sha:
        cmd = ["git", "diff", "--name-status", base_sha, head_sha]
        print(f"🚀 CI/CD Mode: Comparing PR commit range ({base_sha[:7]}...{head_sha[:7]})")
    else:
        # 2. Local Git execution or fallback comparing HEAD against target branch
        base_ref = os.getenv("GITHUB_BASE_REF", "main")
        target_branch = f"origin/{base_ref}"
        cmd = ["git", "diff", "--name-status", f"{target_branch}...HEAD"]
        print(f"🚀 Git Mode: Comparing HEAD against target branch ({target_branch})")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        changes = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            status = parts[0]
            # Handle git file rename (e.g., R100 where parts[1]=old, parts[2]=new)
            file_path = parts[-1] 
            changes.append((status, file_path))
        return changes
    except subprocess.CalledProcessError as e:
        print(f"❌ Error executing git diff command: {e.stderr}")
        sys.exit(1)


def analyze_repository_changes(folder_to_target: dict):
    """Analyzes modified files from git diff and builds dataset refresh payloads grouped by Target.
    
    Args:
        folder_to_target (dict): Dynamic folder-to-target mapping loaded from JSON config.

    Returns:
        tuple: (detected_targets, payloads_by_target, deleted_tables_reasons)
    """
    file_changes = get_git_diff_file_statuses()

    tables_by_target = {}
    external_tmdl_by_target = {}
    deleted_tables_reasons = {}  # Track table deletion events triggering full refresh
    detected_targets = set()

    for status, file_path in file_changes:
        file_path = file_path.strip()
        if not file_path:
            continue

        normalized_path = file_path.replace("\\", "/")
        parts = normalized_path.split("/")

        # 1. Identify Target/Workspace based on the root folder name
        root_folder = parts[0]
        target = folder_to_target.get(root_folder)

        if not target:
            continue  # Ignore files outside monitored workspace folders

        detected_targets.add(target)

        # Initialize tracking data structures for the target workspace
        if target not in tables_by_target:
            tables_by_target[target] = {}
        if target not in external_tmdl_by_target:
            external_tmdl_by_target[target] = set()

        # 2. Inspect if the file modification belongs to a Semantic Model definition
        if ".SemanticModel/definition/" in normalized_path:
            model_folder = next(
                (p for p in parts if p.endswith(".SemanticModel")), None
            )
            model_name = (
                model_folder.replace(".SemanticModel", "")
                if model_folder
                else "UnknownModel"
            )

            is_deleted = status.startswith("D")

            # CASE A: Changes detected inside the 'tables' sub-folder
            if "/definition/tables/" in normalized_path:
                tables_index = parts.index("tables")
                if len(parts) > tables_index + 1:
                    table_file = parts[tables_index + 1]
                    table_name = os.path.splitext(table_file)[0]

                    if is_deleted:
                        # 🚨 Table DELETED -> Force Full Semantic Model Refresh
                        external_tmdl_by_target[target].add(model_name)
                        if target not in deleted_tables_reasons:
                            deleted_tables_reasons[target] = {}
                        if model_name not in deleted_tables_reasons[target]:
                            deleted_tables_reasons[target][model_name] = []
                        deleted_tables_reasons[target][model_name].append(table_name)
                    else:
                        # Table ADDED or MODIFIED -> Eligible for Partial Table Refresh
                        if model_name not in tables_by_target[target]:
                            tables_by_target[target][model_name] = set()
                        tables_by_target[target][model_name].add(table_name)

            # CASE B: Changes in root TMDL files (model.tmdl, relationships.tmdl, etc.)
            # Full Semantic Model Refresh
            elif normalized_path.endswith(".tmdl"):
                external_tmdl_by_target[target].add(model_name)

    # 3. Build the final JSON payload structure grouped by Target
    payloads_by_target = {}

    for target in detected_targets:
        payloads_by_target[target] = {}

        # Priority 1: Full Model Refresh → If any root TMDL file is modified OR any table deleted
        if target in external_tmdl_by_target:
            for model_name in external_tmdl_by_target[target]:
                payloads_by_target[target][model_name] = {
                    "refresh_mode": "full_model",
                    "objects": None,
                }

        # Priority 2: Partial Refresh → Only applied if full model refresh was not triggered
        if target in tables_by_target:
            for model_name, tables in tables_by_target[target].items():
                if model_name not in payloads_by_target[target]:
                    payloads_by_target[target][model_name] = {
                        "refresh_mode": "partial_tables",
                        "objects": [{"table": t} for t in sorted(list(tables))],
                    }

    return detected_targets, payloads_by_target, deleted_tables_reasons


def print_summary(targets: set, payloads: dict, deleted_reasons: dict):
    """Prints a structured, human-readable summary for pipeline log visibility."""
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
                objects = data.get("objects") or []
                tables = [obj["table"] for obj in objects]
                print(f"   📌 Model: {model_name} [Mode: Partial Refresh]")
                for t in tables:
                    print(f"      • Table: {t}")
            elif mode == "full_model":
                print(f"   📌 Model: {model_name} [Mode: Full Model Refresh]")
                deleted_tbls = deleted_reasons.get(target, {}).get(model_name, [])
                if deleted_tbls:
                    print(f"      • Reason: Table deletion detected ({', '.join(deleted_tbls)})")
                else:
                    print("      • Reason: Root TMDL file(s) modified")


if __name__ == "__main__":
    # Load mapping configuration from JSON
    folder_mapping = load_folder_target_mapping()

    # Analyze git changes
    targets, payloads, deleted_reasons = analyze_repository_changes(folder_mapping)

    # Print human-readable logs
    print_summary(targets, payloads, deleted_reasons)

    # Format variables for GitHub Actions environment export
    targets_str = " ".join(sorted(list(targets)))
    payloads_json_str = json.dumps(payloads)
    has_changes_str = str(len(targets) > 0).lower()

    # 1. Export outputs via GITHUB_OUTPUT (for GitHub Actions step outputs)
    github_output = os.getenv("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            f.write(f"has_changes={has_changes_str}\n")
            f.write(f"targets={targets_str}\n")
            f.write(f"refresh_payloads={payloads_json_str}\n")

    # 2. Export variables via GITHUB_ENV (for environment variable access in downstream steps)
    github_env = os.getenv("GITHUB_ENV")
    if github_env:
        with open(github_env, "a", encoding="utf-8") as f:
            f.write(f"TARGETS={targets_str}\n")
            if not targets:
                f.write("SKIP_PIPELINE=true\n")