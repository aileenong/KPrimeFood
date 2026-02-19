import streamlit as st
from supabase import create_client, Client
import pandas as pd
from datetime import datetime

# ---------------- SUPABASE CONNECTION ----------------
SUPABASE_URL = st.secrets["supabase"]["url"]
SUPABASE_KEY = st.secrets["supabase"]["service_role_key"]  # server-side only
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------- DATABASE FUNCTIONS ----------------
def view_items():
    res = supabase.table("items").select("*").execute()
    return pd.DataFrame(res.data)

def delete_all_inventory():
    supabase.table("items").delete().gte("item_id", 0).execute()
    supabase.table("audit_log").insert({
        "item_name": "ALL ITEMS",
        "category": "ALL CATEGORIES",
        "action": "Delete All Inventory",
        "quantity": 0,
        "unit_cost": 0.00,
        "selling_price": 0.00,
        "username": "System"
    }).execute()    

def view_pricing():
    res = supabase.table("pricing_tiers").select("*").execute()
    return pd.DataFrame(res.data)

def view_sales():
    res = supabase.table("sales").select("*").execute()
    return pd.DataFrame(res.data)

def view_sales_by_customer(customer_id):
    res = supabase.table("sales").select("*").eq("customer_id", customer_id).execute()
    return pd.DataFrame(res.data)

def view_customers():
    res = supabase.table("customers").select("*").execute()
    return pd.DataFrame(res.data)

def delete_all_customers():
    # Explicitly delete all rows by using a condition that matches everything
    supabase.table("customers").delete().gte("id", 0).execute()

    # Log the action
    supabase.table("audit_log").insert({
        "item_name": "ALL CUSTOMERS",
        "category": "N/A",
        "action": "Delete All Customers",
        "quantity": 0,
        "unit_cost": 0.00,
        "selling_price": 0.00,
        "username": "System"
    }).execute()

def view_sales_by_customers(customer_id=None):
    query = supabase.table("sales").select("*")
    if customer_id:
        query = query.eq("customer_id", customer_id)
    res = query.execute()
    return pd.DataFrame(res.data)

def view_audit_log(start_date=None, end_date=None):
    query = supabase.table("audit_log").select("*").order("timestamp", desc=True)
    if start_date and end_date:
        query = query.gte("timestamp", str(start_date)).lte("timestamp", str(end_date))
    res = query.execute()
    return pd.DataFrame(res.data)

def get_po_sequence(order_date_sql: str) -> int:
    """Fetch or increment PO sequence for a given date."""
    result = supabase.table("po_sequence").select("seq").eq("date", order_date_sql).execute()
    if result.data:
        seq = result.data[0]["seq"] + 1
        supabase.table("po_sequence").update({"seq": seq}).eq("date", order_date_sql).execute()
    else:
        seq = 1
        supabase.table("po_sequence").insert({"date": order_date_sql, "seq": seq}).execute()
    return seq

def get_customer(customer_id: int) -> dict:
    """Fetch customer details by ID."""
    result = supabase.table("customers").select("*").eq("id", customer_id).execute()
    if result.data:
        return result.data[0]
    return {}

# ---------------- CRUD FUNCTIONS ----------------
def add_or_update_item(item_id, item_name, category, quantity, fridge_no, user):
    # Normalize fridge_no to int if possible
    try:
        fridge_no = int(fridge_no)
    except:
        pass

    action = None

    if item_id and item_id != "Add New":
        # Case 1: Existing item selected
        existing = supabase.table("items").select("*").eq("item_id", item_id).execute()
        if existing.data:
            current_record = existing.data[0]
            current_qty = current_record["quantity"]
            current_fridge = current_record["fridge_no"]

            if str(current_fridge) == str(fridge_no):
                # Same fridge → add to existing quantity
                new_qty = current_qty + quantity
                supabase.table("items").update({
                    "quantity": new_qty
                }).eq("item_id", item_id).execute()
                action = "Update"
            else:
                # Different fridge → create new item row
                supabase.table("items").insert({
                    "item_name": item_name,
                    "category": category,
                    "quantity": quantity,
                    "fridge_no": fridge_no
                }).execute()
                action = "Add (New Fridge)"
        else:
            # No record found → insert new
            supabase.table("items").insert({
                "item_name": item_name,
                "category": category,
                "quantity": quantity,
                "fridge_no": fridge_no
            }).execute()
            action = "Add"
    else:
        # Case 2: New item/category entered
        # ✅ Check if same item/category/fridge already exists
        existing = (
            supabase.table("items")
            .select("*")
            .eq("item_name", item_name)
            .eq("category", category)
            .eq("fridge_no", fridge_no)
            .execute()
        )

        if existing.data:
            # Update quantity instead of inserting duplicate
            current_record = existing.data[0]
            new_qty = current_record["quantity"] + quantity
            supabase.table("items").update({
                "quantity": new_qty
            }).eq("item_id", current_record["item_id"]).execute()
            action = "Update Existing (Duplicate Prevented)"
        else:
            # Insert new record
            supabase.table("items").insert({
                "item_name": item_name,
                "category": category,
                "quantity": quantity,
                "fridge_no": fridge_no
            }).execute()
            action = "Add"

    # Audit log entry
    supabase.table("audit_log").insert({
        "item_name": item_name,
        "category": category,
        "action": action,
        "quantity": quantity,
        "unit_cost": 0.0,
        "selling_price": 0.0,
        "username": user,
        "timestamp": datetime.now().isoformat()
    }).execute()


def add_or_update_item2(item_id, item_name, category, quantity, fridge_no, user):
    # Normalize fridge_no to int if possible
    try:
        fridge_no = int(fridge_no)
    except:
        pass

    # Case 1: If item_id provided, check if record exists
    if item_id and item_id != "Add New":
        existing = supabase.table("items").select("*").eq("item_id", item_id).execute()
        if existing.data:
            current_record = existing.data[0]
            current_qty = current_record["quantity"]
            current_fridge = current_record["fridge_no"]

            if str(current_fridge) == str(fridge_no):
                # Same fridge → add to existing quantity
                new_qty = current_qty + quantity
                supabase.table("items").update({
                    "quantity": new_qty
                }).eq("item_id", item_id).execute()
                action = "Update"
            else:
                # Different fridge → create new item row
                supabase.table("items").insert({
                    "item_name": item_name,
                    "category": category,
                    "quantity": quantity,
                    "fridge_no": fridge_no
                }).execute()
                action = "Add (New Fridge)"
        else:
            # No record found → insert new
            supabase.table("items").insert({
                "item_name": item_name,
                "category": category,
                "quantity": quantity,
                "fridge_no": fridge_no
            }).execute()
            action = "Add"
    else:
        # Case 2: New item
        supabase.table("items").insert({
            "item_name": item_name,
            "category": category,
            "quantity": quantity,
            "fridge_no": fridge_no
        }).execute()
        action = "Add"

    # Audit log entry
    supabase.table("audit_log").insert({
        "item_name": item_name,
        "category": category,
        "action": action,
        "quantity": quantity,
        "unit_cost": 0.0,
        "selling_price": 0.0,
        "username": user,
        "timestamp": datetime.now().isoformat()
    }).execute()

def delete_item(item_id, user):
    res = supabase.table("items").select("*").eq("item_id", item_id).execute()
    if res.data:
        item_details = res.data[0]
        supabase.table("audit_log").insert({
            "item_name": item_details["item_name"],
            "category": item_details["category"],
            "action": "Delete",
            "quantity": item_details["quantity"],
            "unit_cost": 0.00,
            "selling_price": 0.00,
            "username": user
        }).execute()
        supabase.table("items").delete().eq("item_id", item_id).execute()

def get_total_qty(selected_item_name):
    res = supabase.table("items").select("*").eq("item_name", selected_item_name).execute()
    if not res.data:
        return "Item not found."
    total_quantity = sum(r["quantity"] for r in res.data)
    return total_quantity

def record_sale(item_id, quantity, user, customer_id, override_total=None):
    res = supabase.table("items").select("*").eq("item_id", item_id).execute()
    if not res.data:
        return "Item not found."
    item = res.data[0]
    item_name = item["item_name"]
    category = item["category"]

    tier_res = supabase.table("pricing_tiers").select("price_per_unit").eq("item_id", item_id).lte("min_qty", quantity).order("min_qty", desc=True).limit(1).execute()
    if tier_res.data:
        price_per_unit = tier_res.data[0]["price_per_unit"]
    else:
        price_per_unit = 0.00

    selling_price = override_total if override_total else price_per_unit
    total_sale = quantity * selling_price
    overridden_flag = 1 if override_total else 0
    cost = 0.0
    profit = 0.0

    rows = supabase.table("items").select("*").eq("item_name", item_name).execute().data
    qty_to_deduct = quantity
    deduction_log = []
    for r in rows:
        if qty_to_deduct <= 0:
            break
        available = r["quantity"]
        deduct = min(available, qty_to_deduct)
        new_qty = available - deduct
        supabase.table("items").update({"quantity": new_qty}).eq("item_id", r["item_id"]).execute()
        qty_to_deduct -= deduct
        deduction_log.append(f"Fridge {r['fridge_no']}: deducted {deduct}, new qty={new_qty}")

    supabase.table("sales").insert({
        "item_id": item_id,
        "item_name": item_name,
        "quantity": quantity,
        "selling_price": selling_price,
        "total_sale": total_sale,
        "cost": cost,
        "profit": profit,
        "customer_id": customer_id,
        "overridden": overridden_flag
    }).execute()

    supabase.table("audit_log").insert({
        "item_name": item_name,
        "category": category,
        "action": "Sale",
        "quantity": quantity,
        "unit_cost": cost,
        "selling_price": selling_price,
        "username": user
    }).execute()

    return f"Sale recorded. Deduction details:\n" + "\n".join(deduction_log)

def get_tiered_price(item_id: int, quantity: int):
    """
    Fetch the correct tiered price per unit for an item/quantity.
    Returns None if no tier is found.
    """
    response = supabase.table("pricing_tiers").select("price_per_unit") \
        .eq("item_id", item_id) \
        .lte("min_qty", quantity) \
        .or_(f"max_qty.is.null,max_qty.gte.{quantity}") \
        .order("min_qty", desc=True) \
        .limit(1) \
        .execute()

    if not response.data:
        return None
    return response.data[0]["price_per_unit"]

def get_pricing_tiers(item_id: int):
    """Fetch pricing tiers for a given item_id, ordered by min_qty."""
    res = supabase.table("pricing_tiers").select("*").eq("item_id", item_id).order("min_qty").execute()
    return pd.DataFrame(res.data)

def save_pricing_tier(item_id: int, min_qty: int, max_qty: int, price_per_unit: float, label: str):
    """Insert or update a pricing tier."""
    if max_qty == 0:
        existing = (
            supabase.table("pricing_tiers")
            .select("*")
            .eq("item_id", item_id)
            .eq("min_qty", min_qty)
            .is_("max_qty", None)
            .execute()
        )
    else:
        existing = (
            supabase.table("pricing_tiers")
            .select("*")
            .eq("item_id", item_id)
            .eq("min_qty", min_qty)
            .eq("max_qty", max_qty)
            .execute()
        )

    if existing.data:
        if max_qty == 0:
            supabase.table("pricing_tiers").update({
                "price_per_unit": price_per_unit,
                "label": label.strip().upper()
            }).eq("item_id", item_id).eq("min_qty", min_qty).is_("max_qty", None).execute()
        else:
            supabase.table("pricing_tiers").update({
                "price_per_unit": price_per_unit,
                "label": label.strip().upper()
            }).eq("item_id", item_id).eq("min_qty", min_qty).eq("max_qty", max_qty).execute()
        return "updated"
    else:
        supabase.table("pricing_tiers").insert({
            "item_id": item_id,
            "min_qty": min_qty,
            "max_qty": None if max_qty == 0 else max_qty,
            "price_per_unit": price_per_unit,
            "label": label.strip().upper()
        }).execute()
        return "inserted"

def delete_pricing_tier(tier_id: int):
    """Delete a pricing tier by ID."""
    supabase.table("pricing_tiers").delete().eq("id", tier_id).execute()
    return True

def upload_tiered_pricing_to_db(df: pd.DataFrame):
    """
    Process a DataFrame of tiered pricing and update/insert into Supabase.
    Returns a list of skipped item_ids.
    """
    skipped_rows = []

    for _, row in df.iterrows():
        item_id = int(row['item_id'])
        min_qty = int(row['min_qty'])
        max_qty = None if pd.isna(row['max_qty']) else int(row['max_qty'])
        price_per_unit = float(row['price_per_unit'])
        label = str(row['label']).strip().upper()

        # ✅ Check if item exists in items table
        item_check = supabase.table("items").select("item_id").eq("item_id", item_id).execute()
        if not item_check.data:
            skipped_rows.append(item_id)
            continue

        # Check if pricing tier exists
        if max_qty is None:
            existing = (
                supabase.table("pricing_tiers")
                .select("id")
                .eq("item_id", item_id)
                .eq("min_qty", min_qty)
                .is_("max_qty", None)
                .eq("label", label)
                .execute()
            )
        else:
            existing = (
                supabase.table("pricing_tiers")
                .select("id")
                .eq("item_id", item_id)
                .eq("min_qty", min_qty)
                .eq("max_qty", max_qty)
                .eq("label", label)
                .execute()
            )

        if existing.data:
            tier_id = existing.data[0]["id"]
            supabase.table("pricing_tiers").update({
                "price_per_unit": price_per_unit
            }).eq("id", tier_id).execute()
        else:
            supabase.table("pricing_tiers").insert({
                "item_id": item_id,
                "min_qty": min_qty,
                "max_qty": max_qty,
                "price_per_unit": price_per_unit,
                "label": label
            }).execute()

    return skipped_rows

def get_customers():
    """Fetch all customers from Supabase."""
    res = supabase.table("customers").select("*").execute()
    return pd.DataFrame(res.data)

def save_customer(customer_id: int, name: str, phone: str, email: str, address: str):
    """Insert or update a customer record."""
    data = {
        "name": name.strip().upper(),
        "phone": phone.strip(),
        "email": email.strip().upper(),
        "address": address.strip().upper()
    }

    if customer_id:  # Update existing
        supabase.table("customers").update(data).eq("id", customer_id).execute()
        return "updated"
    else:  # Insert new
        supabase.table("customers").insert(data).execute()
        return "inserted"

def delete_customer(customer_id: int):
    """Delete a customer by ID."""
    supabase.table("customers").delete().eq("id", customer_id).execute()
    return True

def get_sales_by_customer(customer_id: int, start_date: str, end_date: str):
    """
    Fetch sales records for a given customer between start_date and end_date.
    Returns a DataFrame.
    """
    query = (
        supabase.table("sales")
        .select("*")
        .eq("customer_id", customer_id)
        .gte("date", str(start_date))
        .lte("date", str(end_date))
        .execute()
    )
    return pd.DataFrame(query.data)

