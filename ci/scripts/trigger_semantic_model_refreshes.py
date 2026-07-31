import json
import os
import sys
from simplepbi import datasets


def trigger_refreshes():
    # 1. Retrieve required environment variables
    targets_env = os.getenv("TARGETS", "").strip()
    payloads_json_str = os.getenv("REFRESH_PAYLOADS", "{}")
    token = os.getenv("TOKEN")

    if not targets_env:
        print("⚠️ No TARGETS defined. Skipping refresh step.")
        return

    if not token:
        print("❌ Error: Bearer TOKEN missing in environment.")
        sys.exit(1)

    try:
        all_payloads = json.loads(payloads_json_str)
    except json.JSONDecodeError:
        print("❌ Error decoding REFRESH_PAYLOADS JSON string.")
        sys.exit(1)

    # Initialize SimplePBI Datasets client
    ds = datasets.Datasets(token)
    targets = targets_env.split()

    print("\n==============================================")
    print("🔄 STARTING SEMANTIC MODEL REFRESH PROCESS (via SimplePBI)")
    print("==============================================")

    for target in targets:
        log_filename = f"deployment_log_{target}.json"

        if not os.path.exists(log_filename):
            print(f"\n⚠️ Deployment log '{log_filename}' not found for target '{target}'. Skipping.")
            continue

        print(f"\n📂 Processing Target: [{target.upper()}]")

        with open(log_filename, "r", encoding="utf-8") as f:
            deploy_log = json.load(f)

        # Extract Workspace ID from the deployment log
        workspace_id = deploy_log.get("test_workspace_id")
        if not workspace_id:
            print(f"❌ Error: 'test_workspace_id' missing in '{log_filename}'.")
            continue

        target_payloads = all_payloads.get(target, {})
        items = deploy_log.get("items", [])

        # Filter only deployed items of type SemanticModel
        semantic_models = [
            item for item in items if item.get("itemType") == "SemanticModel"
        ]

        if not semantic_models:
            print("   ℹ️ No Semantic Models deployed for this target.")
            continue

        for model in semantic_models:
            model_name = model.get("targetItemName")
            dataset_id = model.get("targetItemId")

            # Verify if this model has detected TMDL changes
            if model_name not in target_payloads:
                print(f"   ⏩ Model '{model_name}': No TMDL changes detected. Skipping refresh.")
                continue

            model_config = target_payloads[model_name]
            refresh_mode = model_config.get("refresh_mode")
            objects = model_config.get("objects")  # Contains list of dicts [{"table": "name"}] or None

            print(f"\n   👉 Model: {model_name} (ID: {dataset_id})")
            print(f"      Refresh Mode: {refresh_mode}")
            print(f"      Target Objects: {objects if objects else 'Entire Dataset (Full)'}")

            try:
                # Trigger enhanced refresh using SimplePBI wrapper
                response = ds.enhanced_refresh_dataset_in_group(
                    workspace_id=workspace_id,
                    dataset_id=dataset_id,
                    objects=objects,
                    typeProcessing="Full",
                    commitMode="transactional",
                )

                # SimplePBI returns a requests.Response object (Status 202 Accepted expected)
                status_code = getattr(response, "status_code", None)
                if status_code == 202:
                    print(f"      ✅ Refresh triggered successfully (HTTP 202 Accepted).")
                else:
                    response_text = getattr(response, "text", "No response body")
                    print(f"      ⚠️ Refresh trigger returned status {status_code}: {response_text}")

            except Exception as e:
                print(f"      ❌ Exception during SimplePBI API call: {str(e)}")


if __name__ == "__main__":
    trigger_refreshes()