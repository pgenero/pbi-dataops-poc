
import time
import requests
import os

token = os.getenv("TOKEN")
workspace_id = os.getenv("WORKSPACE_ID")

headers = {
    "Authorization": f"Bearer {token}"
}

def is_synced():
    url = f"https://api.fabric.microsoft.com/v1/workspaces/{workspace_id}/git/status"
    r = requests.get(url, headers=headers)
    data = r.json()
    
    print("Sync status:", data)

    return data.get("status") == "Completed"

for i in range(10):
    if is_synced():
        print("Workspace synced ✅")
        break

    print("Waiting for sync...")
    time.sleep(5)