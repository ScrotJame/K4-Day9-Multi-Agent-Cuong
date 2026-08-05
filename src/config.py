"""
Cấu hình pipeline: API key, model, đường dẫn dữ liệu.

Hỗ trợ 2 provider:
  - Mistral AI: ministral-8b-2512, ministral-3b-2512
  - NVIDIA NIM: meta-llama/llama-3.2-3b-instruct, meta-llama/llama-3.2-1b-instruct
"""

import os
from pathlib import Path

# ---- Tự động đọc .env ----
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val

# ---- Đường dẫn dữ liệu ----
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = str(BASE_DIR / "data")
INPUT_DIR = str(BASE_DIR / "input")
OUTPUT_DIR = str(BASE_DIR / "output")
TRACE_FILE = str(BASE_DIR / "trace.jsonl")
LOGGING_TRACE_FILE = str(BASE_DIR / "logging" / "trace.jsonl")

# ---- Mistral API ----
MISTRAL_API_URL = os.environ.get("MISTRAL_BASE_URL", "https://api.mistral.ai/v1/chat/completions")
MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", os.environ.get("LLM_API_KEY", ""))

# ---- NVIDIA NIM API ----
NVIDIA_BASE_URL = os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
NVIDIA_API_KEY_1 = os.environ.get("NVIDIA_API_KEY_1", "")
NVIDIA_API_KEY_2 = os.environ.get("NVIDIA_API_KEY_2", "")

# ---- Model names (hardcoded in source per README requirement) ----
# Mistral models
COORDINATOR_MODEL = "ministral-8b-2512"
POLICY_MODEL = "ministral-8b-2512"
CUSTOMER_AGENT_MODEL = "ministral-3b-2512"
ORDER_PRODUCT_AGENT_MODEL = "ministral-3b-2512"
DELIVERY_AGENT_MODEL = "ministral-3b-2512"
PAYMENT_AGENT_MODEL = "ministral-3b-2512"

# NVIDIA Build models
VERIFIER_MODEL = "meta/llama-3.2-3b-instruct"

FILES = {
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "order_reviews": "olist_order_reviews_dataset.csv",
    "customers": "olist_customers_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
}

# ---- Retry / rate limit ----
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2
REQUEST_TIMEOUT = 60