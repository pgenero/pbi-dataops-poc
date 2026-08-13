# DevWorkspace Sync and Deploy to Test Script (`sync_workspaces.py`)

## 📌 Overview & Objective
The `sync_workspaces.py` script is a core component of the Microsoft Fabric CI/CD deployment pipeline. Its primary objective is to synchronize the Development workspace with the GitHub repository after a PR from a `feature branch` to the `main branch`, and trigger automated deployments across stages (from **Dev** to **Test**) via Fabric Deployment Pipelines REST APIs.

The image below illustrates the part of the process handled by the script:

![Script Scope](../assets/sync_workspace_scope.png)

> In short, the script is triggered after a pull request is approved for the main branch. This synchronizes the code on GitHub with the content in the Dev workspace related to main. The updated content is then deployed to the Test workspace using Fabric's deployment pipeline via the API. Additionally, the process generates a log file that is stored in a Fabric lakehouse.

---

### Architecture Flow

```mermaid
graph TD
    A[GitHub Actions Workflow] -->|Environment Variables| B(0. Logging Configuration)
    B --> C(1. Environment & Target Setup)
    C --> D{Iterate per Target Workspace}
    D --> E[Configure Workspace Git Credentials]
    D --> F[Get Pre-Sync Status & Changes]
    D --> G[Trigger Git Sync updateFromGit]
    D --> H[Poll Sync Completion]
    D --> I[Build Deployment Payload]
    D --> J[Trigger Deployment Dev -> Test]
    J --> K(4. Execution Summary & Exit Code)
```
---

## 🔸 **0. Logging Configuration**

### **Purpose & Business Logic**

This block initializes Python's native logging library dynamically. It acts as a toggle mechanism between standard runtime outputs (`INFO`) and detailed diagnostic outputs (`DEBUG`). This is intended for error cases where a deep review of the process details is needed.

### **Detailed Mechanics**

- **GitHub Actions Debug Detection:** Automatically evaluates the `ACTIONS_STEP_DEBUG` environment variable set by GitHub when a user clicks *"Re-run jobs with enable debug logging"*.

- **Level Selection:**

    - If `ACTIONS_STEP_DEBUG == "true"`, the log level is set to `logging.DEBUG`.

    - Otherwise, it defaults to `logging.INFO`.

- **Formatting:** Configures log output with standard timestamps, log levels (INFO, DEBUG, ERROR), and descriptive messages for uniform log readability in GitHub step logs.

## 🔸 **1. Environment Setup & Configuration**

### Purpose & Business Logic

Prepares necessary credentials, Pull Request (PR) execution metadata, and target mapping configurations required to authenticate and execute REST API requests against Microsoft Fabric.

### Detailed Mechanics

#### 1.1 Environment Variables Extraction:

- `TOKEN`: Bearer Token for Fabric REST API authentication. It is obtained from the token previously saved in the YAML that executes the Python script.

- `GIT_CONNECTION_ID`: Fabric Git connection reference ID. The ID is stored in GitHub's *Secrets and Variables*. The YAML retrieves it for use in this script.

- `GITHUB_SHA`: Remote commit SHA representing the target code state. 

- `GITHUB_HEAD_REF`: Source branch associated with the Pull Request.

- `GITHUB_ACTOR` & `GITHUB_AUTHOR`: Identifies the user approving and creating the PR for audit logging.

- `PR_TITLE`: Pull Request title message used during deployment note generation.

- `TARGETS`: Space-separated list of target workspace identifiers (passed from upstream steps with `detect_workspace_changes.py`).

#### 1.2 JSON Target Configuration Loading (`fabric_targets.json`):

- Reads `ci/config/fabric_targets.json` to map high-level target names to their respective Fabric IDs:

    - `workspace_id`: Fabric **Development** Workspace ID.
    - `pipeline_id`: Fabric Deployment Pipeline ID.
    - `dev_stage_id`: Source stage ID in Fabric pipeline (not the Workspace ID).
    - `test_stage_id`: Target stage ID in Fabric pipeline (not the Workspace ID).

- **Error Handling:** If the configuration file is missing or invalid, it logs an error and exits immediately (`exit(1)`).

#### 1.3 Global Headers & State:

- Prepares standard API authorization headers (`Bearer {TOKEN}`).

- Initializes `results = []` array to keep track of success/failure statuses per target workspace.

## 🔸 **2. Helper Functions**

### `get_items(workspace_id, token)`

#### Purpose & Business Logic

The `get_items` function acts as helper that uses the Fabric REST API to retrieve a full inventory of artifacts (e.g., Semantic Models, Reports, Notebooks, Pipelines) present in a specified workspace. 

In the scope of this script, this inventory is crucial for resolving the unique `objectId` (GUID) of newly added artifacts. When a new item is pushed from Git, the Git status change log indicates an `"Added"` change state without always providing its generated Workspace Object ID. Fetching the workspace items allows the script to map newly created artifacts by `displayName` and `itemType` to retrieve their corresponding `sourceItemId` before triggering deployment.

#### Detailed Mechanics & API Flow

```mermaid
sequenceDiagram
    autonumber
    participant Script as get_items()
    participant API as Fabric REST API
    
    Script->>API: GET /v1/workspaces/{workspace_id}/items
    Note over Script,API: Auth: Bearer {token}
    
    alt HTTP 200 OK
        API-->>Script: 200 OK (JSON Payload)
        Script->>Script: Extract "value" array (list of items)
        Script-->>Script: Return items list
    else HTTP Error (Status != 200)
        API-->>Script: Error Response (e.g., 401, 404, 500)
        Script->>Script: Log error message
        Script-->>Script: Return empty list []
    end
```

#### Code Breakdown & Input Parameters

- **2.1 Parameters**:

    - `workspace_id (str)`: Target Microsoft Fabric Workspace GUID.

    - `token (str)`: Bearer token authorized to read workspace contents.

- **2.2 Endpoint Construction**:

    - Request URL: 

            https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/items

    - Request Method: `GET`

- **2.3 HTTP Request Execution & Error Handling**:

    - Executes `requests.get()` passing localized authorization headers.

    - **Response Validation**: Checks if `response.status_code != 200`.

        If an error occurs, it logs an explicit error message using `logging.error()` containing the HTTP status code and response body, returning a safe fallback empty list ([]) to prevent script crashes.

- **2.4 Data Extraction**:

    - Parses the JSON response body (`response.json()`).

    - Retrieves the list of workspace items stored under the `"value"` array key using `.get("value", [])`.

## 🔸 **3. Main Execution Loop (Per Target Workspace)**

### Overview

This block iterates through each detected **target** workspace identifier stored in `targets`. It orchestrates the process of loading configurations, configuring workspace Git credentials, evaluating incoming repository changes, triggering the synchronization between GitHub and Microsoft Fabric, and verifying sync completion.

```mermaid
sequenceDiagram
    autonumber
    participant Script as sync_workspaces.py
    participant Config as TARGETS_CONFIG
    participant Fabric as Fabric REST API
    participant GH_Env as GITHUB_ENV File

    Script->>Config: 3.1 Load Workspace Config
    Script->>Fabric: 3.2 PATCH /git/myGitCredentials
    Script->>Fabric: 3.3 GET /git/status (Pre-Sync)
    Fabric-->>Script: Return workspaceHead & changes list
    Script->>Fabric: 3.4 POST /git/updateFromGit
    
    loop 3.5 Poll Sync Completion (Max 10 Retries)
        Script->>Fabric: GET /git/status
        Fabric-->>Script: Return workspaceHead & remoteCommitHash
        alt workspaceHead == remoteCommitHash
            Script->>Script: Sync completed successfully
        else In Progress
            Script->>Script: Wait 5 seconds
        end
    end
    
    Script->>GH_Env: 3.6 Persist WORKSPACE_HEAD_BEFORE
```

### 3.1 Load Target Configuration

#### Purpose & Business Logic
Retrieves the specific target workspace IDs and pipeline identifiers required to interact with the Fabric REST API for the current target in the loop.

#### Detailed Mechanics
- Extracts `target_info` from `TARGETS_CONFIG` dictionary using the lowercase target name (`target.lower()`).
- **Validation:** If the target name is missing in the configuration file, it raises a `ValueError` which is caught at the `try-except` block to log execution failure for that target.
- Stores key identifiers:
  - `workspace_id`: The target Fabric Development Workspace GUID.
  - `pipeline_id`: The Fabric Deployment Pipeline GUID.
  - `dev_stage_id`: Source stage ID in the deployment pipeline.
  - `test_stage_id`: Target stage ID in the deployment pipeline.

### 3.2 Configure Git Credentials

#### Purpose & Business Logic
Configures or updates the workspace's Git connection credentials dynamically prior to triggering sync operations. This ensures that the workspace uses the designated service connection credentials to interact with GitHub without authentication errors.

#### Detailed Mechanics
- **Endpoint:** `PATCH /v1/workspaces/{workspace_id}/git/myGitCredentials`
- **Payload:**
```json
{
  "source": "ConfiguredConnection",
  "connectionId": "<GIT_CONNECTION_ID>"
}
```

### 3.3 Get Workspace Git Status Before Sync

#### Purpose & Business Logic

Queries the workspace Git status before triggering the synchronization process. This allows the script to capture two crucial pieces of metadata:

- The incoming Git delta (`changes` array), which details modified, added, or deleted artifacts.

- The initial workspace commit state (`workspaceHead`).

> 💡 Once a `pull request` is approved on GitHub, the changes aren't automatically published in Fabric. To do this, the process requires a ***synchronization*** between GitHub and Fabric. In this step, we compare the commit HEADs of both environments. If there's a difference, it means Git has changes that haven't been synchronized with Fabric.

#### Detailed Mechanics

- **Endpoint:**  'GET /v1/workspaces/{workspace_id}/git/status'

- Captures `workspaceHead` (the commit hash currently applied to the workspace).

- Stores the `changes` array containing object metadata, item types, identifiers, and change types (`Modified, Added, Deleted`). These changes are later evaluated to construct the deployment payload.

### 3.4 Trigger Sync (Workspace <-> Git Repository)

#### Purpose & Business Logic

Initiates an asynchronous update process (`updateFromGit`) in Fabric to update the Development workspace with the target commit SHA from the GitHub repository (`remoteCommitHash`).

> 💡 At this point, we're synchronizing the **Dev workspace** with the `main branch` on **GitHub**. The `main branch` is the one that received the changes from the `feature branch` when the `pull request` was approved. Now we need to `push` those changes to Fabric so we can then deploy them to **Test**.

#### Detailed Mechanics
- **Endpoint**: `POST /v1/workspaces/{workspace_id}/git/updateFromGit`
- **Payload**:
```json
{
  "remoteCommitHash": "<GITHUB_SHA>",
  "workspaceHead": "<workspace_head>",
  "options": {
    "allowOverrideItems": true
  }
}
```
- `allowOverrideItems`: True ensures that incoming changes from Git overwrite conflicting items existing inside the workspace.

### 3.5 Wait for Sync Completion (Polling)

#### Purpose & Business Logic

Since `updateFromGit` is an asynchronous operation, the script executes a polling loop to monitor the synchronization status, ensuring the workspace reaches the desired commit state before proceeding to deployment building. 

> 💡 If we proceed with deployment without waiting for the sync to complete, we end up deploying outdated artifacts, without the latest Git changes.

#### Detailed Mechanics

- Executes a loop up to 10 times (with a 5-second pause between attempts via *time.sleep(5)*).

- On each iteration, queries `GET /v1/workspaces/{workspace_id}/git/status`.

- Evaluates if `workspace_head == remote_head` (`workspaceHead == remoteCommitHash`).

    - **Match**: Logs completion and breaks out of the polling loop.

    - **Mismatch**: Continues polling and logs status on the first attempt.

### 3.6 Save Pre-Sync Workspace Commit Head

#### Purpose & Business Logic

Exports the synchronized commit hash (`WORKSPACE_HEAD_BEFORE`) to the GitHub Actions environment variable file (`$GITHUB_ENV`). This value is stored for auditing purposes or downstream step references within the workflow pipeline.

#### Detailed Mechanics

- Opens `os.environ['GITHUB_ENV']` in append mode (`'a'`).

- Appends `WORKSPACE_HEAD_BEFORE={workspace_head}`.

- Raises an `Exception` if `workspace_head` could not be retrieved, halting execution to prevent downstream errors.

### 3.7 Build the List of Items for Deployment

#### Purpose & Business Logic

This step evaluates the Git status changes captured prior to the sync operation (`changes` array) and constructs the precise list of items (`items_to_deploy`) that must be included in the downstream Fabric Deployment Pipeline payload. 

Since Microsoft Fabric REST API uses specific item type identifiers for deployments that may differ from internal Git status names, the script standardizes item types via a mapping file (`item_type_mapping.json`). Furthermore, it categorizes changes into three distinct scenarios to extract valid workspace GUIDs (`sourceItemId`) for deployment and logs deleted items for tracking.

```mermaid
flowchart TD
    A[Start: Iterate Git Changes] --> B[Load Item Type Map]
    B --> C[Normalize itemType using map]
    C --> D{Evaluate remoteChange}
    
    D -->|Scenario 1: Modified| E{objectId in identifier?}
    E -->|Yes| F[Add item to items_to_deploy]
    E -->|No| Z[Ignore / Skip]
    
    D -->|Scenario 2: Added| G[Lookup workspace_items by displayName & type]
    G --> H{Item found?}
    H -->|Yes| I[Add item with ws_item ID to items_to_deploy]
    H -->|No| J[Log Warning: No matching workspace item]
    
    D -->|Scenario 3: Deleted| K{objectId in identifier?}
    K -->|Yes| L[Add item to deleted_items list]
    
    F --> M[Next Change]
    I --> M
    J --> M
    L --> M
    Z --> M