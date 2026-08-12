# Detect Workspace Changes Script (`detect_workspace_changes.py`)

## 📌 Overview & Objective
The `detect_workspace_changes.py` script is the core change detection engine for the deployment pipeline. It inspects Git commit differences (`git diff`) between the Pull Request source ***feature branch*** `AND` the ***main branch*** to identify:

1. **Modified Target Pipeline:** Maps modified top-level repository folders to Fabric pipelines using a central JSON configuration. The purpose is to perform workflow operations (including merging to the main branch, deploying within Fabric, and generating log files) per **"target"**.
2. **Semantic Model Granularity:** Analyzes TMDL file modifications to determine whether a semantic model update requires a **Full Model Refresh** or a **Partial Table Refresh**.
3. **Pipeline Control Signals:** Sets environment signals (`SKIP_PIPELINE=true`) if no workspace changes are found, preventing unnecessary deployment step executions.

---

## 🎯 The "Target" Concept

In our Git workflow, a **Target** **is NOT a single Power BI Workspace**. 

> A **Target** is a logical unit that represents a complete data lifecycle for a specific business area or function (for example: *Sales*, *Operations*, or *Finance*). Each Target maps directly to a full Power BI **Deployment Pipeline**, which is always composed of a set of three (3) connected Workspaces: 
> 
> 1. **Development (Dev)**
> 2. **Testing (Test)**
> 3. **Production (Prod)**

#### ⁉️ Why do we call it this way?

Because when we point Git to a specific Target (e.g., target: sales), we are referencing that area's entire structure as a single group. This allows our automation scripts to identify: 

* The **unique Pipeline ID** that links the environments in Power BI.
* The **individual IDs** for each of the 3 Workspaces (Dev, Test, and Prod) belonging to that group.

> **In short:** The Target is the "parent container" that groups the three stages an artifact must go through before reaching the end users.

---

## ⚙️ Description of the script logic

### Function: `load_folder_target_mapping()`

The equivalences between the folders in the Git repository and their corresponding workspaces in Fabric are managed via a dedicated configuration file:

* **File Location:** [ci/config/folder_target_mapping.json](../../ci/config/folder_target_mapping.json)

```json
{
  "DataOps": "sales",
  "ws-finance": "finance",
  "ws-deploy-poc": "operations"
}
```

In the script, this is done with the `load_folder_target_mapping()` function.

**How it works?** It reads the `folder_target_mapping.json` file to recover the dictionary that acts as a "translator". The script use the mapping to assign the detected changes to a target. Example: changes detected by the script in `ws-finance/`, assign it to `finance`."

### Function: `get_git_diff_file_statuses()`

**How it works?** It runs the `git diff --name-status` to identify the files that changed between two versions (base_sha and head_sha), also indicating the type of change (e.g., whether the file was modified, appended, or deleted).

If the script it's running in GitHub Actions (where the commit variables `base_sha` and `head_sha` exist), it compares that specific range of commits. If the script runs locally, it compares the branch against `origin/main`.

### Function: `analyze_repository_changes()`

This is the core analysis engine that inspects changed file paths and builds refresh strategies.

1. *Path Mapping & Filtering:*

    Normalizes slashes (\ -> /) and extracts the root_folder. Checks folder_to_target: If the root folder is not mapped to a Fabric target, the file is ignored.

2. *Semantic Model Inspection:*

    Evaluates if the path contains .SemanticModel/definition/. Then, extracts the model_name (e.g., SalesModel from SalesModel.SemanticModel).

3. *Logic Decision Tree:*

    - Case A — Tables Directory (/definition/tables/):

      - Deleted Tables (D status): Deleting a table disrupts structural relationships. It forces a Full Model Refresh (full_model) and logs the deletion reason.

      - Added or Modified Tables: Adds the table name to tables_by_target to qualify for a Partial Table Refresh (partial_tables).

    - Case B — Root TMDL Files:

    Modifications to root definition files (e.g., model.tmdl, relationships.tmdl, cultures) trigger a mandatory Full Model Refresh (full_model).

4. *Payload Building:*

    - Priority 1 (full_model): If root TMDL files were modified or any table was deleted, refresh_mode: "full_model" is set with objects: None.

    - Priority 2 (partial_tables): If no full refresh was triggered, builds a payload containing refresh_mode: "partial_tables" along with an array of specific table objects [{"table": "TableName"}].

5. *Print Output:*

    Outputs structured, human-readable logging to stdout for GitHub Actions step logs visibility. It displays all detected target workspaces.

6. *Entry Point (if `__name__` == `__main__`:)*

    Coordinates execution and exposes environment variables to subsequent pipeline steps.

    GitHub Actions Output Exports:

    - `GITHUB_OUTPUT`: Writes step outputs (has_changes, targets, refresh_payloads) for downstream steps in the same job.

    - `GITHUB_ENV`: Sets TARGETS environment variable.
---

## 🛠️ Technical Execution Logic

``` mermaid
graph TD
    A[Start Execution] --> B[Load Config: folder_target_mapping.json]
    B --> C[Execute Git Diff between feature-branch and main]
    C --> D[Parse Modified File Paths]
    D --> G[Identify Target Workspace]
    G --> H{Changes in .SemanticModel Folder?}
    H -->|No| I[No Model Refresh - Only Report Changes]
    I --> M
    H -->|Yes| J{Evaluation Logic}
    J -->|Table Added / Modified| K[Flag for Partial Refresh]
    J -->|Table Deleted OR Root TMDL File Changed| L[Flag for Full Model Refresh]
    K --> M[Build JSON Payloads]
    L --> M
    M --> N[Export to GITHUB_OUTPUT & GITHUB_ENV]
```

---

## 🔄 Dataset Refresh Evaluation Matrix

When changes inside a `.SemanticModel/definition/` path are detected, the refresh strategy is categorized according to the following rules:

| Condition |	Refresh Mode Triggered | Description / Reason|
|:--|:--|:--|
| Table TMDL Added/Modified	| partial_tables |	Only the specific table TMDL files altered in definition/tables/ are included in the refresh payload. |
| Table TMDL Deleted |	full_model |	Deleting a table structurally alters model schema/relationships, forcing a full dataset process. |
| Root TMDL File Modified |	full_model	| Modifications to root files (model.tmdl, relationships.tmdl, cultures/, etc.) force a full model refresh. |

---

## 📤 Output Variables Exported

The script exports key outputs to `GITHUB_OUTPUT` and `GITHUB_ENV` for downstream GitHub Action steps:

| Variable Name |	Environment	| Sample Value |	Description |
|:--|:--|:--|:--|
| has_changes |	`GITHUB_OUTPUT` |	true / false |	Indicates whether mapped workspace folder changes were detected.| 
| targets |	`GITHUB_OUTPUT` |	sales finance |	Space-separated string of detected target workspace names.|
| refresh_payloads |	`GITHUB_OUTPUT` |	{"sales": {"SalesModel": {"refresh_mode": "full_model", ...}}}	| JSON dictionary payload containing models and their calculated refresh modes. |
| TARGETS |	`GITHUB_ENV` | 	sales operations |	Exposes target string as an environment variable.|
| SKIP_PIPELINE |	`GITHUB_ENV` |	true |	Written only if targets is empty to bypass subsequent pipeline steps. |
---

## 📄 Dependencies & Prerequisites

Configuration File: [ci/config/folder_target_mapping.json](../../ci/config/folder_target_mapping.json)

**Built-in Modules:** `json`, `os`, `subprocess`, `sys`, `pathlib`

