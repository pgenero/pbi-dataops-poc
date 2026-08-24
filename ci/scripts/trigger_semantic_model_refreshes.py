import json
import os
import sys
import logging
from simplepbi import datasets

# ==============================================================================
# 0. LOGGING CONFIGURATION
# ==============================================================================
# GitHub Actions automatically sets ACTIONS_STEP_DEBUG to 'true' if "Enable debug logging" is checked
if os.getenv("ACTIONS_STEP_DEBUG") == "true":
    log_level = logging.DEBUG
else:
    log_level = logging.INFO

logging.basicConfig(level=log_level, format="%(asctime)s - %(levelname)s - %(message)s")

# ==============================================================================
# 1. CREATE A FUNCTION FOR THE REFRESH
# ==============================================================================
def trigger_refreshes():
    # --- 1.1 Retrieve required environment variables ---
    targets_env = os.getenv("TARGETS", "").strip()
    payloads_json_str = os.getenv("REFRESH_PAYLOADS", "{}")
    token = os.getenv("TOKEN")

    if not targets_env:
        logging.warning("⚠️ No TARGETS defined. Skipping refresh step.")
        return

    if not token:
        logging.error("❌ Error: Bearer TOKEN missing in environment.")
        sys.exit(1)

    try:
        all_payloads = json.loads(payloads_json_str)
    except json.JSONDecodeError as e:
        logging.error(f"❌ Error decoding REFRESH_PAYLOADS JSON string: {e}")
        sys.exit(1)

    # --- 1.2 Initialize SimplePBI Datasets client ---
    ds = datasets.Datasets(token)
    targets = targets_env.split()

    # ==============================================================================
    # 2. LOOP THE REFRESH PER TARGET
    # ==============================================================================
    logging.info("==================================================")
    logging.info("🔄 STARTING SEMANTIC MODEL REFRESH PROCESS")
    logging.info("==================================================")

    # --- 2.1 Loop per Target ---
    for target in targets:
        logging.info(f"📂 Processing Target: [{target.upper()}]")
        log_filename = f"deployment_log_{target}.json"

        if not os.path.exists(log_filename):
            logging.warning(f"⚠️ Deployment log '{log_filename}' not found for target [{target}]. Skipping.")
            continue

        try:
            with open(log_filename, "r", encoding="utf-8") as f:
                deploy_log = json.load(f)
        except Exception as e:
            logging.error(f"❌ Failed to parse log file '{log_filename}': {e}")
            continue

        # --- 2.2 Extract Workspace ID from the deployment log ---
        workspace_id = deploy_log.get("test_workspace_id")
        if not workspace_id:
            logging.error(f"❌ Error: 'test_workspace_id' missing in '{log_filename}'.")
            continue

        target_payloads = all_payloads.get(target, {})
        items = deploy_log.get("items", [])

        # --- 2.3 Filter from the deployed items only SemanticModel type ---
        semantic_models = [
            item for item in items if item.get("itemType") == "SemanticModel"
        ]

        if not semantic_models:
            logging.info(f"ℹ️ No Semantic Models deployed for target [{target}].")
            continue

        for model in semantic_models:
            model_name = model.get("targetItemName")
            dataset_id = model.get("targetItemId")

            # --- 2.4 Verify if this model has detected TMDL changes ---
            if model_name not in target_payloads:
                logging.info(f"⏩ Model '{model_name}': No TMDL changes detected. Skipping refresh.")
                continue

            model_config = target_payloads[model_name]
            refresh_mode = model_config.get("refresh_mode")
            objects = model_config.get("objects")  # Contains list of dicts [{"table": "name"}] or None

            logging.info(f"👉 Model: {model_name} (ID: {dataset_id})")
            logging.info(f"   • Refresh Mode: {refresh_mode}")
            logging.info(f"   • Target Objects: {objects if objects else 'Entire Dataset (Full)'}")

            try:
                # --- 2.5 Trigger enhanced refresh using SimplePBI wrapper ---
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
                    logging.info(f"   ✅ Refresh triggered successfully (HTTP 202 Accepted).")
                else:
                    response_text = getattr(response, "text", "No response body")
                    logging.warning(f"   ⚠️ Refresh trigger returned status {status_code}: {response_text}")

            except Exception as e:
                logging.error(f"   ❌ Exception during SimplePBI API call for '{model_name}': {str(e)}")

# ==============================================================================
# 3. INVOKE THE FUNCTION AND TRIGGER THE REFRESH
# ==============================================================================
if __name__ == "__main__":
    trigger_refreshes()