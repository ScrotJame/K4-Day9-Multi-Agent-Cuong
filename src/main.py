"""
Entry point: đọc 50 case JSON từ input/, chạy multi-agent pipeline song song (parallel batch),
ghi output JSON + trace.jsonl + output.zip.

Cách chạy:
    python -m src.main
"""

import os
import json
import sys
import zipfile
import concurrent.futures as cf
from threading import Lock

from . import config
from .data_loader import OlistData
from .orchestrator import investigate_case, TraceLogger


def process_single_case(fname: str, olist: OlistData, trace: TraceLogger, lock: Lock):
    input_path = os.path.join(config.INPUT_DIR, fname)
    with open(input_path, "r", encoding="utf-8") as f:
        case_input = json.load(f)

    case_id = case_input["case_id"]
    order_id = case_input["customer_request"]["claimed_order_id"]

    try:
        case_data = olist.get_full_case_data(order_id)
        output = investigate_case(case_id, order_id, case_data, trace)
    except Exception as e:
        print(f"  [error] {case_id}: {e}")
        output = {
            "case_id": case_id,
            "error": str(e),
        }

    output_path = os.path.join(config.OUTPUT_DIR, fname)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    with lock:
        primary = output.get('case_assessment', {}).get('primary_issue', 'error')
        refund = output.get('financial_resolution', {}).get('recommended_refund_brl', '?')
        print(f"[{case_id}] order={order_id} -> {primary} | refund={refund}")

    return case_id


def create_submission_zip():
    zip_path = os.path.join(config.BASE_DIR, "output.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        output_files = sorted([
            f for f in os.listdir(config.OUTPUT_DIR)
            if f.startswith("EC_") and f.endswith(".json")
        ])
        for fname in output_files:
            file_path = os.path.join(config.OUTPUT_DIR, fname)
            zipf.write(file_path, arcname=fname)
    print(f"[zip] Đã tạo file submission: {zip_path} (chứa {len(output_files)} files)")


def main():
    if not config.MISTRAL_API_KEY:
        print("[error] Chưa set MISTRAL_API_KEY trong .env")
        sys.exit(1)

    print("[info] Đang load dữ liệu Olist...")
    olist = OlistData()
    print("[info] Load xong.")

    input_files = sorted([
        f for f in os.listdir(config.INPUT_DIR)
        if f.startswith("EC_") and f.endswith(".json")
    ])
    print(f"[info] Bắt đầu chạy song song {len(input_files)} cases...")

    if not input_files:
        print("[error] Không tìm thấy file EC_xxx.json trong input/")
        sys.exit(1)

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(config.LOGGING_TRACE_FILE), exist_ok=True)

    trace = TraceLogger()
    lock = Lock()

    # Chạy song song 5 worker cases
    with cf.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [
            executor.submit(process_single_case, fname, olist, trace, lock)
            for fname in input_files
        ]
        cf.wait(futures)

    # Ghi trace.jsonl
    _write_trace(config.TRACE_FILE, trace)
    _write_trace(config.LOGGING_TRACE_FILE, trace)

    # Nén output.zip
    create_submission_zip()

    print(f"\n[done] Đã hoàn tất 50 cases! Output saved to {config.OUTPUT_DIR}")


def _write_trace(path: str, trace: TraceLogger):
    with open(path, "w", encoding="utf-8") as f:
        for entry in trace.get_entries():
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
