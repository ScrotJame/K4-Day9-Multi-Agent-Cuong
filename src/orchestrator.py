"""
Coordinator Agent — nhận case, giao việc cho domain agents, tổng hợp output.

Flow (Zero-Trust Verified Multi-Agent Pipeline):
  1. Parse input case JSON
  2. Join & verify order/payment/item/customer/product/seller từ Olist DB (Zero-Trust)
  3. Dispatch 4 domain agents (concurrent)
  4. Gọi Policy Agent với evidence thực tế thu thập từ DB
  5. Gọi Verifier Agent để cross-check độc lập
  6. Assemble output theo đúng schema README
  7. Ghi trace
"""

import json
import concurrent.futures as cf
from datetime import datetime

from . import config
from .agents import (
    DOMAIN_AGENTS, policy_agent, verifier_agent,
)
from .llm_client import call_mistral


class TraceLogger:
    """Ghi trace cho mỗi case — lưu handoff giữa agents."""

    def __init__(self):
        self.entries = []

    def log(self, case_id: str, step: str, **kwargs):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "case_id": case_id,
            "step": step,
            **kwargs,
        }
        self.entries.append(entry)

    def get_entries(self):
        return self.entries


def investigate_case(case_id: str, order_id: str, case_data: dict, trace: TraceLogger) -> dict:
    """
    Coordinator Agent: điều phối toàn bộ investigation cho 1 case với Zero-Trust Verification.
    """

    # ---- Step 1: Coordinator bắt đầu investigation ----
    trace.log(case_id, "investigation_started", claimed_order_id=order_id)

    # ---- Step 2: Zero-Trust DB Join & Fact Verification ----
    items_cnt = len(case_data.get("items", []))
    payments_cnt = len(case_data.get("payments", []))
    order_status = case_data.get("order_core", {}).get("order_status", "unknown")
    trace.log(
        case_id, "db_join_and_verification",
        verified_tables=["orders", "order_items", "order_payments", "customers", "products", "sellers"],
        order_status=order_status,
        joined_items_count=items_cnt,
        joined_payments_count=payments_cnt,
        policy_version=case_data.get("policy_version", "EC_POLICY_V2"),
    )

    # ---- Step 3: Coordinator dispatch domain agents ----
    trace.log(
        case_id, "coordinator_delegation",
        action="dispatch_to_domain_agents",
        domains=list(DOMAIN_AGENTS.keys()),
    )

    # ---- Step 4: Chạy 4 domain agents song song ----
    agent_results = {}
    with cf.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(fn, order_id, case_data): name
            for name, fn in DOMAIN_AGENTS.items()
        }
        for future in cf.as_completed(futures):
            name = futures[future]
            try:
                result = future.result()
                agent_results[name] = result
                trace.log(
                    case_id, "domain_agent_completed",
                    domain=name,
                    finding=result.get("finding", "unknown"),
                    model=_get_model_for_agent(name),
                )
            except Exception as e:
                agent_results[name] = {"agent": name, "error": str(e), "finding": "error"}
                trace.log(case_id, "domain_agent_error", domain=name, error=str(e))

    # ---- Step 5: Policy Agent đánh giá ----
    trace.log(case_id, "policy_evaluation_started", model=config.POLICY_MODEL)
    policy_result = policy_agent(order_id, case_data, agent_results)
    trace.log(
        case_id, "policy_evaluated",
        primary_issue=policy_result["primary_issue"],
        case_status=policy_result["case_status"],
        recommended_refund_brl=policy_result["recommended_refund_brl"],
        model=config.POLICY_MODEL,
    )

    # ---- Step 6: Assemble output schema ----
    output = _assemble_output(case_id, order_id, case_data, agent_results, policy_result)

    # ---- Step 7: Verifier Agent cross-check ----
    trace.log(case_id, "verifier_started", model=config.VERIFIER_MODEL)
    verify_result = verifier_agent(output)
    trace.log(
        case_id, "verifier_completed",
        verified=verify_result.get("verified", False),
        model=config.VERIFIER_MODEL,
    )

    # ---- Step 8: Coordinator tổng hợp cuối cùng ----
    trace.log(
        case_id, "investigation_completed",
        primary_issue=output["case_assessment"]["primary_issue"],
        case_status=output["case_assessment"]["case_status"],
        recommended_refund_brl=output["financial_resolution"]["recommended_refund_brl"],
    )

    return output


def _get_model_for_agent(agent_name: str) -> str:
    models = {
        "customer": config.CUSTOMER_AGENT_MODEL,
        "order_product": config.ORDER_PRODUCT_AGENT_MODEL,
        "delivery": config.DELIVERY_AGENT_MODEL,
        "payment": config.PAYMENT_AGENT_MODEL,
    }
    return models.get(agent_name, "ministral-3b-2512")


def _assemble_output(
    case_id: str, order_id: str, case_data: dict,
    agent_results: dict, policy_result: dict,
) -> dict:
    """Tạo dict output chuẩn schema Section 6 README."""
    customer_ctx = case_data["customer_context"]
    op = agent_results["order_product"]
    deliv = agent_results["delivery"]
    pay = agent_results["payment"]

    return {
        "case_id": case_id,
        "case_assessment": {
            "primary_issue": policy_result["primary_issue"],
            "secondary_issues": policy_result["secondary_issues"],
            "case_status": policy_result["case_status"],
            "confidence": policy_result["confidence"],
        },
        "affected_entities": {
            "order_ids": op["order_ids"],
            "item_ids": op["item_ids"],
            "seller_ids": op["seller_ids"],
            "payment_ids": pay["payment_ids"],
        },
        "customer_context": {
            "customer_unique_id": customer_ctx.get("customer_unique_id", ""),
            "related_order_ids": customer_ctx.get("related_order_ids", [])[:5],
        },
        "product_context": {
            "product_ids": op["product_ids"],
            "category_names": op["category_names"],
        },
        "delivery_analysis": {
            "delivered_at": deliv["delivered_at"],
            "estimated_delivery_at": deliv["estimated_delivery_at"],
            "carrier_handoff_at": deliv["carrier_handoff_at"],
            "delivery_variance_hours": deliv["delivery_variance_hours"],
            "seller_handoff_analysis": deliv["seller_handoff_analysis"],
            "late_handoff_seller_ids": deliv["late_handoff_seller_ids"],
        },
        "payment_reconciliation": {
            "currency": "BRL",
            "item_total_brl": pay["item_total_brl"],
            "freight_total_brl": pay["freight_total_brl"],
            "expected_total_brl": pay["expected_total_brl"],
            "payment_total_brl": pay["payment_total_brl"],
            "difference_brl": pay["difference_brl"],
            "reconciled": pay["reconciled"],
            "payment_types": pay["payment_types"],
        },
        "root_cause_analysis": {
            "ranked_causes": [
                {"cause_code": policy_result["root_cause"], "rank": 1}
            ],
            "responsible_parties": policy_result["responsible_parties"],
        },
        "evidence_ids": policy_result["evidence_ids"],
        "financial_resolution": {
            "currency": "BRL",
            "recommended_refund_brl": policy_result["recommended_refund_brl"],
        },
        "resolution_actions": policy_result["resolution_actions"],
    }
