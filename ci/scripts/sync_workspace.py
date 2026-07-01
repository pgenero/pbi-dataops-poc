
import os
import requests
import time

token = os.getenv("TOKEN")
workspace_id = os.getenv("WORKSPACE_ID")
remote_commit = os.getenv("GITHUB_SHA")

headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

# 1. Get current commit status in the workspace
status_url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/git/status"

status_response = requests.get(status_url, headers=headers)
status_data = status_response.json()

print("Workspace status:", status_data)

workspace_head = status_data.get("workspaceHead") or ""

print(f"Workspace head: {workspace_head}")

if not workspace_head:
    raise Exception("No se pudo obtener workspaceHead")

# 2. Build payload
payload = {
    "remoteCommitHash": remote_commit,
    "workspaceHead": workspace_head,
    "options": {
        "allowOverrideItems": True
    }
}

# 3. Run sync
sync_url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/git/updateFromGit"

sync_response = requests.post(sync_url, headers=headers, json=payload)

if not sync_response.text or sync_response.text == "null":
    print("No changes to sync (already in sync)")
else:
    print("Sync triggered:", sync_response.text)


# 4. Wait until sync is completed
print("Waiting for sync...")

for i in range(10):
    status_check = requests.get(status_url, headers=headers).json()
    
    print("Sync state:", status_check)

    if status_check.get("status") == "Completed":
        print("✅ Sync completed")
        break

    time.sleep(5)

# 5. Commits details
print("Remote commit:", remote_commit)
print("Workspace head before:", workspace_head)
