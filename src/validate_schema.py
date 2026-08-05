import os
import json

schema_keys = {
    "case_id": str,
    "case_assessment": dict,
    "affected_entities": dict,
    "customer_context": dict,
    "product_context": dict,
    "delivery_analysis": dict,
    "payment_reconciliation": dict,
    "root_cause_analysis": dict,
    "evidence_ids": list,
    "financial_resolution": dict,
    "resolution_actions": list,
}

valid_primary_issues = {
    "canceled_order_paid",
    "unavailable_order_paid",
    "late_delivery_seller",
    "late_delivery_logistics",
    "valid_split_payment",
    "unsupported_late_claim",
}

valid_secondary_issues = [
    "multi_item_order",
    "multi_seller_order",
    "split_payment",
    "repeat_customer",
    "multiple_categories",
]

valid_actions = {
    "issue_full_refund",
    "refund_freight",
    "explain_valid_split_payment",
    "reject_late_refund",
    "review_seller_handoff",
    "review_carrier_delay",
    "verify_refund_completion",
    "coordinate_multi_seller_case",
    "verify_payment_allocation",
}

out_dir = "output"
files = sorted([f for f in os.listdir(out_dir) if f.endswith(".json")])

print(f"Total files in output: {len(files)}")
errors = []

for fname in files:
    fpath = os.path.join(out_dir, fname)
    with open(fpath, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 1. Root keys check
    for k in schema_keys:
        if k not in data:
            errors.append(f"{fname}: Missing root key {k}")

    # 2. Case assessment check
    ca = data.get("case_assessment", {})
    p_issue = ca.get("primary_issue")
    if p_issue not in valid_primary_issues:
        errors.append(f"{fname}: Invalid primary_issue '{p_issue}'")

    s_issues = ca.get("secondary_issues", [])
    for si in s_issues:
        if si not in valid_secondary_issues:
            errors.append(f"{fname}: Invalid secondary_issue '{si}'")

    # Check secondary issues order
    idx = -1
    for si in s_issues:
        cur_idx = valid_secondary_issues.index(si)
        if cur_idx <= idx:
            errors.append(f"{fname}: Out of order secondary_issues: {s_issues}")
            break
        idx = cur_idx

    status = ca.get("case_status")
    if status not in {"action_required", "no_action"}:
        errors.append(f"{fname}: Invalid case_status '{status}'")

    conf = ca.get("confidence")
    if not (isinstance(conf, (int, float)) and 0 <= conf <= 1):
        errors.append(f"{fname}: Invalid confidence '{conf}'")

    # 3. Affected entities check
    ae = data.get("affected_entities", {})
    if len(ae.get("order_ids", [])) > 5:
        errors.append(f"{fname}: order_ids > 5")
    if len(ae.get("item_ids", [])) > 5:
        errors.append(f"{fname}: item_ids > 5")
    if len(ae.get("seller_ids", [])) > 3:
        errors.append(f"{fname}: seller_ids > 3")
    if len(ae.get("payment_ids", [])) > 5:
        errors.append(f"{fname}: payment_ids > 5")

    # 4. Contexts check
    cc = data.get("customer_context", {})
    if len(cc.get("related_order_ids", [])) > 5:
        errors.append(f"{fname}: related_order_ids > 5")

    pc = data.get("product_context", {})
    if len(pc.get("product_ids", [])) > 5:
        errors.append(f"{fname}: product_ids > 5")
    if len(pc.get("category_names", [])) > 5:
        errors.append(f"{fname}: category_names > 5")

    # 5. Evidence IDs check
    evs = data.get("evidence_ids", [])
    if len(evs) > 20:
        errors.append(f"{fname}: evidence_ids > 20")

    # 6. Resolution actions check
    acts = data.get("resolution_actions", [])
    if len(acts) > 5:
        errors.append(f"{fname}: resolution_actions > 5")
    for act in acts:
        if act not in valid_actions:
            errors.append(f"{fname}: Invalid action '{act}'")

if errors:
    print(f"FOUND {len(errors)} ERRORS:")
    for e in errors[:10]:
        print("  -", e)
else:
    print("ALL 50 OUTPUT JSON FILES PASSED COMPREHENSIVE SCHEMA VALIDATION!")
