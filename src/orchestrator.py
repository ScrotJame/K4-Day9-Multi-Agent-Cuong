"""
Coordinator Agent — nhận case, giao việc cho domain agents, tổng hợp output.

Flow:
  1. Parse input case JSON
  2. Extract data từ OlistData
  3. Dispatch 4 domain agents (concurrent)
  4. Gọi Policy Agent với evidence từ domain agents
  5. Gọi Verifier Agent để cross-check
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
    Coordinator Agent: điều phối toàn bộ investigation cho 1 case.
    Gọi LLM (ministral-8b-2512) để quyết định và tổng hợp.
    """

    # ---- Step 1: Coordinator bắt đầu investigation ----
    trace.log(case_id, "investigation_started", claimed_order_id=order_id)

    # ---- Step 2: Coordinator dispatch domain agents ----
    trace.log(
        case_id, "coordinator_delegation",
        action="dispatch_to_domain_agents",
        domains=list(DOMAIN_AGENTS.keys()),
    )

    # ---- Step 3: Chạy 4 domain agents song song ----
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

    # ---- Step 4: Policy Agent đánh giá ----
    trace.log(case_id, "policy_evaluation_started", model=config.POLICY_MODEL)
    policy_result = policy_agent(order_id, case_data, agent_results)
    trace.log(
        case_id, "policy_evaluated",
        primary_issue=policy_result["primary_issue"],
        case_status=policy_result["case_status"],
        recommended_refund_brl=policy_result["recommended_refund_brl"],
        model=config.POLICY_MODEL,
    )

    # ---- Step 5: Assemble output schema ----
    output = _assemble_output(case_id, order_id, case_data, agent_results, policy_result)

    # ---- Step 6: Verifier Agent cross-check ----
    trace.log(case_id, "verifier_started", model=config.VERIFIER_MODEL)
    verify_result = verifier_agent(output)
    trace.log(
        case_id, "verifier_completed",
        verified=verify_result.get("verified", False),
        model=config.VERIFIER_MODEL,
    )

    # ---- Step 7: Coordinator tổng hợp cuối cùng ----
    trace.log(
        case_id, "investigation_completed",
        primary_issue=output["case_assessment"]["primary_issue"],
        case_status=output["case_assessment"]["case_status"],
        recommended_refund_brl=output["financial_resolution"]["recommended_refund_brl"],
    )

    return output


def _get_model_for_agent(agent_name: str) -> str:
    """Trả về tên model cho từng agent."""
    models = {
        "customer": config.CUSTOMER_AGENT_MODEL,
        "order_product": config.ORDER_PRODUCT_AGENT_MODEL,
        "delivery": config.DELIVERY_AGENT_MODEL,
        "payment": config.PAYMENT_AGENT_MODEL,
    }
    return models.get(agent_name, "unknown")


def _assemble_output(
    case_id: str, order_id: str, case_data: dict,
    agent_results: dict, policy_result: dict,
) -> dict:
    """Lắp ráp output theo đúng schema README."""
    customer = agent_results.get("customer", {})
    order_prod = agent_results.get("order_product", {})
    delivery = agent_results.get("delivery", {})
    payment = agent_results.get("payment", {})
    items = case_data.get("items", [])

    # delivery_analysis — null cho order không có delivery data
    delivery_analysis = {
        "delivered_at": delivery.get("delivered_at"),
        "estimated_delivery_at": delivery.get("estimated_delivery_at"),
        "carrier_handoff_at": delivery.get("carrier_handoff_at"),
        "delivery_variance_hours": delivery.get("delivery_variance_hours"),
        "seller_handoff_analysis": delivery.get("seller_handoff_analysis", []) if items else [],
        "late_handoff_seller_ids": delivery.get("late_handoff_seller_ids", []) if items else [],
    }

    # payment_reconciliation
    payment_reconciliation = {
        "currency": "BRL",
        "item_total_brl": payment.get("item_total_brl"),
        "freight_total_brl": payment.get("freight_total_brl"),
        "expected_total_brl": payment.get("expected_total_brl"),
        "payment_total_brl": payment.get("payment_total_brl", 0.0),
        "difference_brl": payment.get("difference_brl"),
        "reconciled": payment.get("reconciled"),
        "payment_types": payment.get("payment_types", []),
    }

    # root_cause_analysis
    root_cause_analysis = {
        "ranked_causes": [
            {"cause_code": policy_result["root_cause"], "rank": 1}
        ],
        "responsible_parties": policy_result.get("responsible_parties", []),
    }

    return {
        "case_id": case_id,
        "case_assessment": {
            "primary_issue": policy_result["primary_issue"],
            "secondary_issues": policy_result["secondary_issues"],
            "case_status": policy_result["case_status"],
            "confidence": policy_result["confidence"],
        },
        "affected_entities": {
            "order_ids": order_prod.get("order_ids", [order_id]),
            "item_ids": order_prod.get("item_ids", []),
            "seller_ids": order_prod.get("seller_ids", []),
            "payment_ids": payment.get("payment_ids", []),
        },
        "customer_context": {
            "customer_unique_id": customer.get("customer_unique_id"),
            "related_order_ids": customer.get("related_order_ids", []),
        },
        "product_context": {
            "product_ids": order_prod.get("product_ids", []),
            "category_names": order_prod.get("category_names", []),
        },
        "delivery_analysis": delivery_analysis,
        "payment_reconciliation": payment_reconciliation,
        "root_cause_analysis": root_cause_analysis,
        "evidence_ids": policy_result.get("evidence_ids", []),
        "financial_resolution": {
            "currency": "BRL",
            "recommended_refund_brl": policy_result["recommended_refund_brl"],
        },
        "resolution_actions": policy_result["resolution_actions"],
    }
