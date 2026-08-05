"""
Load và truy vấn dữ liệu Olist cho từng order_id.

Thiết kế: load 1 lần vào RAM (dataset Olist ~100k order, đủ nhỏ), sau đó mỗi
case chỉ cần filter theo order_id / customer_unique_id.
"""

import os
import pandas as pd
from . import config


class OlistData:
    def __init__(self, data_dir: str = None):
        data_dir = data_dir or config.DATA_DIR
        self.orders = self._read(data_dir, "orders")
        self.order_items = self._read(data_dir, "order_items")
        self.order_payments = self._read(data_dir, "order_payments")
        self.order_reviews = self._read(data_dir, "order_reviews")
        self.customers = self._read(data_dir, "customers")
        self.products = self._read(data_dir, "products")
        self.sellers = self._read(data_dir, "sellers")
        self.category_translation = self._read(data_dir, "category_translation")

        # Parse các cột ngày tháng quan trọng để so sánh timestamp
        date_cols = [
            "order_purchase_timestamp", "order_approved_at",
            "order_delivered_carrier_date", "order_delivered_customer_date",
            "order_estimated_delivery_date",
        ]
        for col in date_cols:
            if col in self.orders.columns:
                self.orders[col] = pd.to_datetime(self.orders[col], errors="coerce")

        if "shipping_limit_date" in self.order_items.columns:
            self.order_items["shipping_limit_date"] = pd.to_datetime(
                self.order_items["shipping_limit_date"], errors="coerce"
            )

    def _read(self, data_dir, key):
        path = os.path.join(data_dir, config.FILES[key])
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"Không tìm thấy file '{config.FILES[key]}' trong {data_dir}."
            )
        return pd.read_csv(path)

    def get_order_core(self, order_id: str) -> dict:
        """Trạng thái đơn + các mốc thời gian."""
        row = self.orders[self.orders["order_id"] == order_id]
        if row.empty:
            return {}
        r = row.iloc[0]
        return {
            "order_id": order_id,
            "order_status": r.get("order_status"),
            "order_purchase_timestamp": self._fmt(r.get("order_purchase_timestamp")),
            "order_approved_at": self._fmt(r.get("order_approved_at")),
            "order_delivered_carrier_date": self._fmt(r.get("order_delivered_carrier_date")),
            "order_delivered_customer_date": self._fmt(r.get("order_delivered_customer_date")),
            "order_estimated_delivery_date": self._fmt(r.get("order_estimated_delivery_date")),
            "customer_id": r.get("customer_id"),
        }

    def get_items(self, order_id: str) -> list:
        """Item, seller, shipping_limit_date, price, freight, category_name."""
        items = self.order_items[self.order_items["order_id"] == order_id]
        out = []
        for _, it in items.iterrows():
            pid = it.get("product_id")
            prod = self.products[self.products["product_id"] == pid]
            cat = None
            if not prod.empty:
                c = prod.iloc[0].get("product_category_name")
                if c and not pd.isna(c):
                    cat = str(c)

            out.append({
                "order_item_id": int(it.get("order_item_id", 0)),
                "product_id": pid,
                "seller_id": it.get("seller_id"),
                "price": round(float(it.get("price", 0) or 0), 2),
                "freight_value": round(float(it.get("freight_value", 0) or 0), 2),
                "shipping_limit_date": self._fmt(it.get("shipping_limit_date")),
                "category_name": cat,
            })
        return out

    def get_payments(self, order_id: str) -> list:
        """Payment rows với payment_sequential."""
        pays = self.order_payments[self.order_payments["order_id"] == order_id]
        return [{
            "payment_sequential": int(p.get("payment_sequential", 0)),
            "payment_type": str(p.get("payment_type")),
            "payment_installments": int(p.get("payment_installments", 0) or 0),
            "payment_value": round(float(p.get("payment_value", 0) or 0), 2),
        } for _, p in pays.iterrows()]

    def get_customer_context(self, order_id: str) -> dict:
        """Customer unique ID + related orders (loại trừ order hiện tại)."""
        order_row = self.orders[self.orders["order_id"] == order_id]
        if order_row.empty:
            return {"customer_unique_id": None, "related_order_ids": []}

        customer_id = order_row.iloc[0]["customer_id"]
        cust_row = self.customers[self.customers["customer_id"] == customer_id]
        if cust_row.empty:
            return {"customer_unique_id": None, "related_order_ids": []}

        unique_id = str(cust_row.iloc[0]["customer_unique_id"])

        all_cust_ids = self.customers[
            self.customers["customer_unique_id"] == unique_id
        ]["customer_id"].tolist()

        all_orders = self.orders[
            self.orders["customer_id"].isin(all_cust_ids)
        ]["order_id"].tolist()

        related = [oid for oid in all_orders if oid != order_id]

        return {
            "customer_unique_id": unique_id,
            "related_order_ids": related[:5],  # max 5
        }

    def get_full_case_data(self, order_id: str) -> dict:
        """Gom toàn bộ dữ liệu thô cho tất cả domain agents."""
        return {
            "order_core": self.get_order_core(order_id),
            "items": self.get_items(order_id),
            "payments": self.get_payments(order_id),
            "customer_context": self.get_customer_context(order_id),
        }

    @staticmethod
    def _fmt(val):
        if val is None or pd.isna(val):
            return None
        s = str(val)
        if "." in s:
            s = s.split(".")[0]
        return s
