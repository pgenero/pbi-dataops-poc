
import os
import requests
import time

token = os.getenv("TOKEN")
workspace_id = os.getenv("WORKSPACE_ID")
connection_id = os.getenv("GIT_CONNECTION_ID")
remote_commit = os.getenv("GITHUB_SHA")

headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

# ✅ 1. CONFIGURAR CREDENCIALES (NUEVO)
cred_url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/git/myGitCredentials"

cred_payload = {
    "source": "ConfiguredConnection",
    "connectionId": connection_id
}

cred_response = requests.patch(cred_url, headers=headers, json=cred_payload)
print("Git credentials configured:", cred_response.text)

# ✅ 2. OBTENER STATUS
status_url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/git/status"

status_response = requests.get(status_url, headers=headers)
status_data = status_response.json()

print("Workspace status:", status_data)

workspace_head = status_data.get("workspaceHead") or ""

# ✅ 3. SYNC
sync_url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/git/updateFromGit"

payload = {
    "remoteCommitHash": remote_commit,
    "workspaceHead": workspace_head,
    "options": {
        "allowOverrideItems": True
    }
}

sync_response = requests.post(sync_url, headers=headers, json=payload)

print("Sync response:", sync_response.text)

# ✅ 4. WAIT
for i in range(10):
    status_check = requests.get(status_url, headers=headers).json()

    workspace_head = status_check.get("workspaceHead")
    remote_head = status_check.get("remoteCommitHash")
    changes = status_check.get("changes", [])

    # ✅ Mostrar SOLO transición relevante
    print(f"[Check {i+1}] workspaceHead={workspace_head} vs remote={remote_head}")

    # ✅ condición de fin clara
    if workspace_head == remote_head:
        print("✅ Sync completed (commits are aligned)")
        break

    time.sleep(5)


# ✅ 5. Commits details
print("Remote commit:", remote_commit)
print("Workspace head before:", workspace_head)
