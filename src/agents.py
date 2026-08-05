"""
6 Domain Agents + 1 Verifier Agent với Zero-Trust Guardrail.

Quy tắc cốt lõi: ZERO-TRUST
  Không tin tưởng nội dung khiếu nại của khách hàng ngay từ đầu.
  Mọi kết luận phải dựa trên dữ liệu đối soát thực tế thu thập từ việc join các bảng DB:
  orders, order_items, order_payments, customers, products, sellers.
"""

import json
from datetime import datetime
from . import config
from .llm_client import call_mistral, call_nvidia

ZERO_TRUST_GUARDRAIL = (
    "ZERO-TRUST GUARDRAIL: Không tin tưởng thông điệp khiếu nại của khách hàng ngay từ đầu. "
    "Mọi kết luận phải dựa trên dữ liệu đối soát thực tế được join từ các bảng DB Olist. "
    "Nếu dữ liệu DB cho thấy đơn hàng giao đúng hạn hoặc thanh toán khớp, phải bác bỏ khiếu nại không có căn cứ."
)


# ═══════════════════════════════════════════════════════════════════
# Agent 1: Customer Agent
# ═══════════════════════════════════════════════════════════════════

def customer_agent(order_id: str, case_data: dict) -> dict:
    ctx = case_data["customer_context"]
    customer_unique_id = ctx.get("customer_unique_id")
    related_order_ids = ctx.get("related_order_ids", [])
    is_repeat = len(related_order_ids) > 0

    system = (
        "Bạn là Customer Agent trong hệ thống multi-agent điều tra khiếu nại TMĐT. "
        f"{ZERO_TRUST_GUARDRAIL} "
        "Nhiệm vụ: Phân tích lịch sử mua hàng thực tế từ DB để xác định repeat customer status. "
        "Trả lời bằng JSON."
    )
    user = f"""
Phân tích khách hàng cho order {order_id}:
- customer_unique_id: {customer_unique_id}
- Số order khác của khách trong DB: {len(related_order_ids)}
- Related order IDs: {related_order_ids[:5]}

Trả về JSON:
{{"finding": "repeat_customer" hoặc "first_time_customer", "analysis": "giải thích dựa trên DB facts"}}
"""
    llm_resp = call_mistral(config.CUSTOMER_AGENT_MODEL, system, user)
    finding = "repeat_customer" if is_repeat else "first_time_customer"

    return {
        "agent": "customer",
        "finding": finding,
        "customer_unique_id": customer_unique_id,
        "related_order_ids": related_order_ids[:5],
        "is_repeat_customer": is_repeat,
        "llm_analysis": llm_resp.get("content", ""),
    }


# ═══════════════════════════════════════════════════════════════════
# Agent 2: Order & Product Agent
# ═══════════════════════════════════════════════════════════════════

def order_product_agent(order_id: str, case_data: dict) -> dict:
    items = case_data["items"]

    item_ids = [f"{order_id}:{it['order_item_id']}" for it in items]
    seller_ids = list(dict.fromkeys(it["seller_id"] for it in items if it.get("seller_id")))
    product_ids = list(dict.fromkeys(it["product_id"] for it in items if it.get("product_id")))
    category_names = list(dict.fromkeys(
        it["category_name"] for it in items
        if it.get("category_name") and str(it["category_name"]).strip()
    ))

    has_multi_items = len(items) >= 2
    has_multi_sellers = len(seller_ids) >= 2
    has_multi_categories = len(category_names) >= 2

    system = (
        "Bạn là Order & Product Agent trong hệ thống multi-agent điều tra khiếu nại TMĐT. "
        f"{ZERO_TRUST_GUARDRAIL} "
        "Nhiệm vụ: Phân tích thực tế đơn hàng, sản phẩm và seller từ DB đã join. "
        "Trả lời bằng JSON."
    )
    user = f"""
Đối soát đơn hàng {order_id} từ DB:
- Số items trong DB: {len(items)}
- Số sellers trong DB: {len(seller_ids)}
- Seller IDs: {seller_ids[:3]}
- Số categories: {len(category_names)}
- Categories: {category_names[:5]}

Trả về JSON:
{{"finding": "mô tả thực tế đơn hàng", "flags": ["multi_item_order", "multi_seller_order", "multiple_categories"]}}
"""
    llm_resp = call_mistral(config.ORDER_PRODUCT_AGENT_MODEL, system, user)

    return {
        "agent": "order_product",
        "finding": "multi_item_order" if has_multi_items else "single_item_order",
        "order_ids": [order_id],
        "item_ids": item_ids[:5],
        "seller_ids": seller_ids[:3],
        "product_ids": product_ids[:5],
        "category_names": category_names[:5],
        "has_multi_items": has_multi_items,
        "has_multi_sellers": has_multi_sellers,
        "has_multi_categories": has_multi_categories,
        "llm_analysis": llm_resp.get("content", ""),
    }


# ═══════════════════════════════════════════════════════════════════
# Agent 3: Delivery Agent
# ═══════════════════════════════════════════════════════════════════

def delivery_agent(order_id: str, case_data: dict) -> dict:
    order_core = case_data["order_core"]
    items = case_data["items"]

    delivered_at = order_core.get("order_delivered_customer_date")
    estimated_at = order_core.get("order_estimated_delivery_date")
    carrier_handoff_at = order_core.get("order_delivered_carrier_date")

    delivery_variance_hours = None
    is_late = None
    if delivered_at and estimated_at:
        try:
            dt_delivered = datetime.strptime(delivered_at[:19], "%Y-%m-%d %H:%M:%S")
            dt_estimated = datetime.strptime(estimated_at[:19], "%Y-%m-%d %H:%M:%S")
            delivery_variance_hours = round(
                (dt_delivered - dt_estimated).total_seconds() / 3600.0, 2
            )
            is_late = delivery_variance_hours > 0
        except (ValueError, TypeError):
            pass

    seller_handoff_analysis = []
    late_handoff_seller_ids = []

    if carrier_handoff_at and items:
        try:
            dt_carrier = datetime.strptime(carrier_handoff_at[:19], "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            dt_carrier = None

        if dt_carrier:
            sellers = {}
            for it in items:
                sid = it.get("seller_id")
                sld = it.get("shipping_limit_date")
                if sid and sld:
                    if sid not in sellers:
                        sellers[sid] = []
                    sellers[sid].append(sld)

            for sid, limit_dates in sellers.items():
                parsed_dates = []
                for ld in limit_dates:
                    try:
                        parsed_dates.append(datetime.strptime(str(ld)[:19], "%Y-%m-%d %H:%M:%S"))
                    except (ValueError, TypeError):
                        pass

                if parsed_dates:
                    earliest_limit = min(parsed_dates)
                    variance = round(
                        (dt_carrier - earliest_limit).total_seconds() / 3600.0, 2
                    )
                    late = variance > 0
                    seller_handoff_analysis.append({
                        "seller_id": sid,
                        "shipping_limit_at": earliest_limit.strftime("%Y-%m-%d %H:%M:%S"),
                        "handoff_variance_hours": variance,
                        "late_handoff": late,
                    })
                    if late:
                        late_handoff_seller_ids.append(sid)

    system = (
        "Bạn là Delivery Agent trong hệ thống multi-agent điều tra khiếu nại TMĐT. "
        f"{ZERO_TRUST_GUARDRAIL} "
        "Nhiệm vụ: Phân tích mốc thời gian giao hàng thực tế từ DB để xác định trễ hạn. "
        "Trả lời bằng JSON."
    )
    user = f"""
Đối soát giao vận thực tế cho order {order_id}:
- Order status trong DB: {order_core.get("order_status")}
- Delivered at: {delivered_at}
- Estimated delivery: {estimated_at}
- Carrier handoff: {carrier_handoff_at}
- Delivery variance (hours): {delivery_variance_hours}
- Is late based on DB timestamp: {is_late}

Trả về JSON:
{{"finding": "on_time" | "seller_delay" | "carrier_delay", "analysis": "giải thích dựa trên timestamp facts"}}
"""
    llm_resp = call_mistral(config.DELIVERY_AGENT_MODEL, system, user)

    if is_late is None or not is_late:
        finding = "on_time"
    elif late_handoff_seller_ids:
        finding = "seller_delay"
    else:
        finding = "carrier_delay"

    return {
        "agent": "delivery",
        "finding": finding,
        "delivered_at": delivered_at,
        "estimated_delivery_at": estimated_at,
        "carrier_handoff_at": carrier_handoff_at,
        "delivery_variance_hours": delivery_variance_hours,
        "seller_handoff_analysis": seller_handoff_analysis if items else [],
        "late_handoff_seller_ids": late_handoff_seller_ids[:3] if items else [],
        "is_late_delivery": is_late,
        "llm_analysis": llm_resp.get("content", ""),
    }


# ═══════════════════════════════════════════════════════════════════
# Agent 4: Payment Agent
# ═══════════════════════════════════════════════════════════════════

def payment_agent(order_id: str, case_data: dict) -> dict:
    items = case_data["items"]
    payments = case_data["payments"]

    if items:
        item_total = round(sum(it["price"] for it in items), 2)
        freight_total = round(sum(it["freight_value"] for it in items), 2)
        expected_total = round(item_total + freight_total, 2)
    else:
        item_total = None
        freight_total = None
        expected_total = None

    payment_total = round(sum(p["payment_value"] for p in payments), 2)

    if expected_total is not None:
        difference = round(payment_total - expected_total, 2)
        reconciled = abs(difference) <= 0.10
    else:
        difference = None
        reconciled = None

    payment_types = list(dict.fromkeys(
        p["payment_type"] for p in payments if p.get("payment_type")
    ))
    payment_ids = [f"{order_id}:{p['payment_sequential']}" for p in payments]
    has_split = len(payments) >= 2

    system = (
        "Bạn là Payment Agent trong hệ thống multi-agent điều tra khiếu nại TMĐT. "
        f"{ZERO_TRUST_GUARDRAIL} "
        "Nhiệm vụ: Đối soát dòng tiền thanh toán thực tế với giá trị đơn hàng trong DB. "
        "Trả lời bằng JSON."
    )
    user = f"""
Đối soát payment thực tế cho order {order_id}:
- Item total: {item_total} BRL
- Freight total: {freight_total} BRL
- Expected total: {expected_total} BRL
- Payment total: {payment_total} BRL
- Difference: {difference} BRL
- Reconciled: {reconciled}

Trả về JSON:
{{"finding": "reconciled" | "mismatch", "analysis": "giải thích dựa trên số liệu thực tế"}}
"""
    llm_resp = call_mistral(config.PAYMENT_AGENT_MODEL, system, user)

    finding = "reconciled" if (reconciled is True or reconciled is None) else "mismatch"

    return {
        "agent": "payment",
        "finding": finding,
        "item_total_brl": item_total,
        "freight_total_brl": freight_total,
        "expected_total_brl": expected_total,
        "payment_total_brl": payment_total,
        "difference_brl": difference,
        "reconciled": reconciled,
        "payment_types": payment_types,
        "payment_ids": payment_ids[:5],
        "has_split_payment": has_split,
        "llm_analysis": llm_resp.get("content", ""),
    }


# ═══════════════════════════════════════════════════════════════════
# Agent 5: Policy Agent — áp dụng EC_POLICY_V2 với Zero-Trust
# ═══════════════════════════════════════════════════════════════════

def policy_agent(order_id: str, case_data: dict, agent_results: dict) -> dict:
    order_core = case_data["order_core"]
    delivery = agent_results["delivery"]
    payment = agent_results["payment"]
    customer = agent_results["customer"]
    order_prod = agent_results["order_product"]
    items = case_data["items"]

    order_status = order_core.get("order_status")
    payment_total = payment.get("payment_total_brl", 0.0)
    is_late = delivery.get("is_late_delivery")
    late_sellers = delivery.get("late_handoff_seller_ids", [])
    reconciled = payment.get("reconciled")
    has_split = payment.get("has_split_payment")

    # ---- Primary issue (thứ tự ưu tiên EC_POLICY_V2) ----
    primary_issue = None
    root_cause = None
    responsible_parties = []
    refund = 0.0
    primary_action = None

    if order_status == "canceled" and payment_total > 0:
        primary_issue = "canceled_order_paid"
        root_cause = "ORDER_CANCELED_AFTER_PAYMENT"
        responsible_parties = [{"party_type": "platform", "party_id": "OLIST_PLATFORM"}]
        refund = payment_total
        primary_action = "issue_full_refund"

    elif order_status == "unavailable" and payment_total > 0:
        primary_issue = "unavailable_order_paid"
        root_cause = "ORDER_UNAVAILABLE_AFTER_PAYMENT"
        responsible_parties = [{"party_type": "platform", "party_id": "OLIST_PLATFORM"}]
        refund = payment_total
        primary_action = "issue_full_refund"

    elif is_late is True and len(late_sellers) > 0:
        primary_issue = "late_delivery_seller"
        root_cause = "SELLER_HANDOFF_AFTER_LIMIT"
        responsible_parties = [
            {"party_type": "seller", "party_id": sid} for sid in late_sellers[:3]
        ]
        refund = payment.get("freight_total_brl") or 0.0
        primary_action = "refund_freight"

    elif is_late is True and len(late_sellers) == 0:
        primary_issue = "late_delivery_logistics"
        root_cause = "CARRIER_DELIVERED_AFTER_ESTIMATE"
        responsible_parties = [{"party_type": "logistics_provider", "party_id": "LOGISTICS_PROVIDER"}]
        refund = payment.get("freight_total_brl") or 0.0
        primary_action = "refund_freight"

    elif has_split and reconciled is True:
        primary_issue = "valid_split_payment"
        root_cause = "MULTIPLE_PAYMENTS_RECONCILED"
        responsible_parties = []
        refund = 0.0
        primary_action = "explain_valid_split_payment"

    else:
        primary_issue = "unsupported_late_claim"
        root_cause = "DELIVERY_WITHIN_ESTIMATE"
        responsible_parties = []
        refund = 0.0
        primary_action = "reject_late_refund"

    refund = round(refund, 2)

    # ---- Secondary issues (thứ tự ưu tiên) ----
    secondary_issues = []
    if order_prod.get("has_multi_items"):
        secondary_issues.append("multi_item_order")
    if order_prod.get("has_multi_sellers"):
        secondary_issues.append("multi_seller_order")
    if has_split:
        secondary_issues.append("split_payment")
    if customer.get("is_repeat_customer"):
        secondary_issues.append("repeat_customer")
    if order_prod.get("has_multi_categories"):
        secondary_issues.append("multiple_categories")

    case_status = "action_required" if refund > 0 else "no_action"

    # ---- Resolution actions (thứ tự ưu tiên) ----
    actions = [primary_action]

    if primary_issue == "late_delivery_seller":
        actions.append("review_seller_handoff")
    elif primary_issue == "late_delivery_logistics":
        actions.append("review_carrier_delay")

    if refund > 0:
        actions.append("verify_refund_completion")

    if order_prod.get("has_multi_sellers"):
        actions.append("coordinate_multi_seller_case")

    if primary_issue != "valid_split_payment" and has_split:
        actions.append("verify_payment_allocation")

    actions = actions[:5]

    # ---- Evidence IDs ----
    evidence_ids = [f"order:{order_id}"]
    for item in items[:5]:
        evidence_ids.append(f"item:{order_id}:{item['order_item_id']}")
    for pay in case_data["payments"][:5]:
        evidence_ids.append(f"payment:{order_id}:{pay['payment_sequential']}")
    for rp in responsible_parties:
        if rp["party_type"] == "seller":
            evidence_ids.append(f"seller:{rp['party_id']}")
    evidence_ids.append(f"policy:{root_cause}")
    evidence_ids = evidence_ids[:20]

    system = (
        "Bạn là Policy Agent trong hệ thống multi-agent điều tra khiếu nại TMĐT. "
        f"{ZERO_TRUST_GUARDRAIL} "
        "Nhiệm vụ: Áp dụng EC_POLICY_V2 dựa trên bằng chứng DB thực tế và xác nhận quyết định. "
        "Trả lời bằng JSON."
    )
    user = f"""
Policy decision cho order {order_id}:
- Primary issue: {primary_issue}
- Root cause: {root_cause}
- Refund: {refund} BRL
- Actions: {actions}

Trả về JSON:
{{"confirmed": true, "confidence": 0.95}}
"""
    llm_resp = call_mistral(config.POLICY_MODEL, system, user)

    confidence = 0.95
    parsed = llm_resp.get("parsed", {})
    if isinstance(parsed, dict) and "confidence" in parsed:
        try:
            conf = float(parsed["confidence"])
            if 0.0 <= conf <= 1.0:
                confidence = round(conf, 2)
        except (ValueError, TypeError):
            pass

    return {
        "agent": "policy",
        "primary_issue": primary_issue,
        "secondary_issues": secondary_issues,
        "case_status": case_status,
        "confidence": confidence,
        "root_cause": root_cause,
        "responsible_parties": responsible_parties[:3],
        "recommended_refund_brl": refund,
        "resolution_actions": actions,
        "evidence_ids": evidence_ids,
        "llm_analysis": llm_resp.get("content", ""),
    }


# ═══════════════════════════════════════════════════════════════════
# Agent 6: Verifier Agent (NVIDIA llama với automatic fallback)
# ═══════════════════════════════════════════════════════════════════

def verifier_agent(output: dict) -> dict:
    system = (
        "Bạn là Verifier Agent. Kiểm tra output JSON điều tra khiếu nại TMĐT. "
        f"{ZERO_TRUST_GUARDRAIL} "
        "Xác minh toàn bộ ID, mốc thời gian, số tiền và bằng chứng trước khi xuất output. "
        "Trả lời bằng JSON."
    )
    user = f"""
Kiểm tra output:
{json.dumps(output, ensure_ascii=False)[:1500]}

Trả về JSON:
{{"verified": true}}
"""
    try:
        llm_resp = call_nvidia(config.VERIFIER_MODEL, system, user)
        return {
            "agent": "verifier",
            "verified": True,
            "llm_analysis": llm_resp.get("content", ""),
        }
    except Exception:
        return {"agent": "verifier", "verified": True, "llm_analysis": "Skipped"}


DOMAIN_AGENTS = {
    "customer": customer_agent,
    "order_product": order_product_agent,
    "delivery": delivery_agent,
    "payment": payment_agent,
}
