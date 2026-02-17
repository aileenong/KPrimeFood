import streamlit as st
from streamlit_option_menu import option_menu
import pandas as pd
import plotly.express as px
import fitz  # PyMuPDF
import os
import io
import base64
import cv2
from pyzbar.pyzbar import decode
import datetime
from datetime import datetime, date
import calendar

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
)
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfgen import canvas

# ✅ Import Supabase database functions
from db_supabase import (
    view_items,
    view_pricing,
    view_sales,
    view_sales_by_customer,
    view_customers,
    delete_all_customers,
    view_sales_by_customers,
    view_audit_log,
    add_or_update_item,
    delete_item,
    delete_all_inventory,
    get_total_qty,
    record_sale
)

# ---------------- SESSION STATE INIT ----------------
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'menu' not in st.session_state:
    st.session_state.menu = "Landing"
if 'username' not in st.session_state:
    st.session_state.username = ""

if "item_name" not in st.session_state:
    st.session_state.item_name = ""
if "category" not in st.session_state:
    st.session_state.category = ""
if "quantity" not in st.session_state:
    st.session_state.quantity = 1
if "fridge_no" not in st.session_state:
    st.session_state.fridge_no = ""

# ---------------- Pagination Utility ----------------
def paginate_dataframe(df, page_size=20):
    total_rows = len(df)
    if total_rows == 0:
        return df, 1
    total_pages = (total_rows // page_size) + (1 if total_rows % page_size else 0)
    page = st.number_input("Page", min_value=1, max_value=total_pages, value=1)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    return df.iloc[start_idx:end_idx], total_pages

# ---------------- LOGOUT FUNCTION ----------------
def logout():
    st.session_state.logged_in = False
    st.session_state.menu = "Landing"
    st.session_state.username = ""

# ----------------- Manage Pricing Tiers -----------------
def manage_pricing_tiers():
    st.title("Manage Pricing Tiers")

    # Select item first
    items_df = view_items()
    if items_df.empty:
        st.warning("No items found.")
        return

    item_label = st.selectbox(
        "Select Item",
        items_df.apply(lambda row: f"{row['item_id']} - {row['item_name']}", axis=1)
    )
    item_id = int(item_label.split(" - ")[0])
    item_name = item_label.split(" - ")[1]

    # Show existing tiers
    from db_supabase import supabase
    res = supabase.table("pricing_tiers").select("*").eq("item_id", item_id).order("min_qty").execute()
    tiers = pd.DataFrame(res.data)

    if not tiers.empty:
        st.subheader("Existing Pricing Tiers")
        tiers["max_qty"] = tiers["max_qty"].fillna("∞")
        tiers["price_per_unit"] = tiers["price_per_unit"].map(lambda x: f"{x:.2f}")
        st.dataframe(tiers, width='stretch')
    else:
        st.info("No pricing tiers defined for this item yet.")

    st.markdown("---")

    # ✅ Collapsible Add/Update section
    with st.expander("➕ Add / Update Pricing Tier", expanded=False):
        min_qty = st.number_input("Minimum Quantity", min_value=1)
        max_qty = st.number_input("Maximum Quantity (0 = unlimited)", min_value=0)
        price_per_unit = st.number_input("Price per Unit", min_value=0.0, format="%.2f")
        label = st.text_input("Tier Label (optional)", value=item_name)

        if st.button("Save Tier"):
            # Check if tier exists
            if max_qty == 0:
                existing = (
                    supabase.table("pricing_tiers")
                    .select("*")
                    .eq("item_id", item_id)
                    .eq("min_qty", min_qty)
                    .is_("max_qty", None)   # ✅ use .is_ for NULL
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
                # Update
                if max_qty == 0:
                    (
                        supabase.table("pricing_tiers")
                        .update({
                            "price_per_unit": price_per_unit,
                            "label": label.strip().upper()
                        })
                        .eq("item_id", item_id)
                        .eq("min_qty", min_qty)
                        .is_("max_qty", None)
                        .execute()
                    )
                else:
                    (
                        supabase.table("pricing_tiers")
                        .update({
                            "price_per_unit": price_per_unit,
                            "label": label.strip().upper()
                        })
                        .eq("item_id", item_id)
                        .eq("min_qty", min_qty)
                        .eq("max_qty", max_qty)
                        .execute()
                    )

                st.success(f"Updated existing pricing tier for {item_name}.")
                st.rerun()
            else:
                # Insert
                supabase.table("pricing_tiers").insert({
                    "item_id": item_id,
                    "min_qty": min_qty,
                    "max_qty": None if max_qty == 0 else max_qty,  # ✅ None becomes SQL NULL
                    "price_per_unit": price_per_unit,
                    "label": label.strip().upper()
                }).execute()
                st.success("Added new Pricing tier successfully!")
                st.rerun()

    # ✅ Collapsible Delete section
    if not tiers.empty:
        with st.expander("🗑️ Delete a Tier", expanded=False):
            st.subheader("Delete a Tier")
            tier_ids = ["Select Tier to Delete"] + [
                f"{t['id']} (min {t['min_qty']}, max {t['max_qty'] if t['max_qty'] is not None else '∞'})"
                for _, t in tiers.iterrows()
            ]
            tier_to_delete = st.selectbox("Select Tier to Delete", tier_ids)
            if st.button("Delete Tier") and tier_to_delete != "Select Tier to Delete":
                tier_id = int(tier_to_delete.split()[0])
                supabase.table("pricing_tiers").delete().eq("id", tier_id).execute()
                st.success("Tier deleted successfully!")
                st.rerun()

# ---------------- Upload Tiered Pricing ----------------
def upload_tiered_pricing(uploaded_file):
    if uploaded_file is None:
        st.error("No file uploaded.")
        return

    # Determine file type and read accordingly
    file_ext = os.path.splitext(uploaded_file.name)[1].lower()
    if file_ext == '.csv':
        df = pd.read_csv(uploaded_file)
    elif file_ext in ['.xlsx', '.xls']:
        df = pd.read_excel(uploaded_file, engine='openpyxl' if file_ext == '.xlsx' else 'xlrd')
    else:
        raise ValueError("Unsupported file format. Please upload a CSV or Excel file.")

    from db_supabase import supabase

    skipped_rows = []

    # Process each pricing tier in the file
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
            continue  # Skip this row

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
            # Update price_per_unit if record exists
            tier_id = existing.data[0]["id"]
            supabase.table("pricing_tiers").update({
                "price_per_unit": price_per_unit
            }).eq("id", tier_id).execute()
        else:
            # Insert new record if not found
            supabase.table("pricing_tiers").insert({
                "item_id": item_id,
                "min_qty": min_qty,
                "max_qty": max_qty,
                "price_per_unit": price_per_unit,
                "label": label
            }).execute()

    if skipped_rows:
        st.warning(f"Skipped rows with invalid item_id(s): {skipped_rows}")
    else:
        st.success("Pricing Tiers updated or inserted successfully!")

# ---------------- LOGIN PAGE ----------------
if not st.session_state.logged_in:
    if os.path.exists("kprime.jpg"):
        st.image("Kprime.jpg", width=250)
    st.title("Welcome to Steak Haven Inventory")
    st.write("Your choice for premium quality meat")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        if username == "admin" and password == "1234":
            st.session_state.logged_in = True
            st.session_state.menu = "Home"
            st.session_state.username = username
            st.rerun()
        else:
            st.error("Invalid credentials")

# ---------------- MAIN APP ----------------
elif st.session_state.logged_in:
    if os.path.exists("KPrime.jpg"):
        st.sidebar.image("KPrime.jpg", width=150)
    st.sidebar.title("Menu")
    st.sidebar.button("Logout", on_click=logout)
    st.sidebar.header("Settings")
    stock_threshold = st.sidebar.number_input("Set Stock Alert Threshold", min_value=0, value=5)

    with st.sidebar:
        main_menu = option_menu(
            "Main Menu",
            ["Home", "Inventory", "Pricing", "Customer", "Reports"],
            icons=["house", "box", "list", "people", "bar-chart"],
            menu_icon="cast",
            default_index=0
        )

        if main_menu == "Home":
            menu = option_menu("Home", ["Home"], icons=["house"])
        elif main_menu == "Inventory":
            menu = option_menu("Inventory", [
                "View Inventory",
                "Manage Stock",
                "File Upload (Items)",
                "Delete All Inventory"
            ], icons=["plus-circle", "list", "pencil", "upload", "trash"])
        elif main_menu == "Pricing":
            menu = option_menu("Pricing", [
                "View Pricing Tiers",
                "File Upload (Pricing)",
                "Manage Pricing Tiers"
            ], icons=["list", "upload", "pencil"])
        elif main_menu == "Customer":
            menu = option_menu("Customer", [
                "Manage Customers",
                "View Sale for a Customer",
                "Add Customer",
                "Record Sale",
                "Customer Statement of Account",
                "Delete All Customers"
            ], icons=["person-plus", "people", "gear", "clipboard", "file-text", "trash"])
        elif main_menu == "Reports":
            menu = option_menu("Reports", [
                "Profit/Loss Report",
                "View Audit Log",
                "Generate Purchase Order",
                "Price Change Impact Report"
            ], icons=["graph-up", "book", "file-earmark-text", "bar-chart"])

    st.session_state.menu = menu
    st.write(f"Selected: {main_menu} → {menu}")

    # ---------------- HOME ----------------
    if menu == "Home":
        st.title("Dashboard")
        items_df = view_items()
        sales_df = view_sales()
        if not items_df.empty:
            st.subheader("Inventory Summary")
            st.metric("Total Items", len(items_df))
            fig = px.bar(items_df, x='category', y='quantity', color='category', title="Stock by Category")
            st.plotly_chart(fig)
        if not sales_df.empty:
            st.subheader("Sales Summary")
            fig2 = px.line(sales_df, x='date', y='profit', title="Profit Trend Over Time")
            st.plotly_chart(fig2)

    # ---------------- VIEW INVENTORY ----------------
    elif menu == "View Inventory":
        st.title("Current Inventory")
        data = view_items()
        if data.empty:
            st.warning("No items found.")
        else:
            paged_df, total_pages = paginate_dataframe(data, page_size=100)
            st.write(f"Showing {len(paged_df)} rows (Page size: 100)")
            st.dataframe(paged_df[['item_id','item_name','category','quantity','fridge_no']])
            csv_inventory = data.to_csv(index=False)
            st.download_button("Download Inventory CSV", data=csv_inventory, file_name="inventory.csv", mime="text/csv")

    # ---------------- MANAGE STOCK ----------------
    elif menu == "Manage Stock":
        st.title("Manage Stock")
        items_df = view_items()
        if items_df.empty:
            st.warning("No items found.")
        else:
            st.subheader("Current Inventory")
            st.dataframe(items_df[['item_id','item_name','category','quantity','fridge_no']])

        with st.expander("➕ Add or Update Stock", expanded=False):
            existing_categories = sorted(items_df['category'].dropna().unique()) if not items_df.empty else []
            category_options = ["Add New"] + existing_categories
            if not items_df.empty:
                item_options = ["Add New"] + [f"{row['item_id']} - {row['item_name']}" for _, row in items_df.iterrows()]
            else:
                item_options = ["Add New"]

            selected_item = st.selectbox("Select Item", item_options)
            current_stock = None

            if selected_item != "Add New":
                selected_item_id = int(selected_item.split(" - ")[0])
                selected_item_name = selected_item.split(" - ")[1]
                item_rows = items_df[items_df['item_name'] == selected_item_name]
                if not item_rows.empty:
                    st.session_state.selected_category = item_rows.iloc[0]['category']
                    category_name = st.session_state.selected_category
                    current_stock = item_rows['quantity'].sum()
                    st.info(f"Stock Currently On Hand: {current_stock}")
                    st.write("Per-Fridge Breakdown:")
                    st.dataframe(item_rows[['fridge_no','quantity']])
                else:
                    st.warning(f"No records found for item '{selected_item}'.")
                item_id = selected_item_id
                item_name = selected_item_name
            else:
                selected_category = st.selectbox("Select Category", category_options)
                category_name = selected_category
                if selected_category == "Add New":
                    category_name = st.text_input("Enter New Category Name")
                item_name = st.text_input("Enter New Item Name", value=st.session_state.item_name)
                item_id = None  # ✅ Important: no bigint error

            quantity = st.number_input("Quantity to Add", min_value=1, value=st.session_state.quantity)
            fridge_no = st.text_input("Fridge No", value=st.session_state.fridge_no)

            if st.button("Save"):
                if item_name and category_name:
                    add_or_update_item(item_id, item_name.strip().upper(), category_name.strip().upper(), quantity, fridge_no, st.session_state.username)
                    st.success(f"Item '{item_name}' in category '{category_name}' updated successfully!")
                    st.rerun()
                else:
                    st.error("Please provide valid item and category names.")

        with st.expander("🗑️ Delete Item", expanded=False):
            if items_df.empty:
                st.warning("No items to delete.")
            else:
                items_df['label'] = items_df.apply(lambda row: f"{row['item_id']} - {row['category']} - {row['item_name']}", axis=1)
                selected_label = st.selectbox("Select Item to Delete", items_df['label'])
                item_id = int(selected_label.split(" - ")[0])
                if st.button("Delete"):
                    delete_item(item_id, st.session_state.username)
                    st.success(f"Item with ID {item_id} deleted successfully!")
                    st.rerun()

    # ---------------- FILE UPLOAD (ITEMS) ----------------
    elif menu == "File Upload (Items)":
        st.title("File Upload (Items)")
        uploaded_file = st.file_uploader("Upload CSV or Excel file", type=["csv", "xlsx", "xls"])
        if uploaded_file is not None:
            file_ext = os.path.splitext(uploaded_file.name)[1].lower()
            if file_ext == ".csv":
                df = pd.read_csv(uploaded_file)
            else:
                df = pd.read_excel(uploaded_file)
            required_cols = ["item_name", "category", "quantity", "fridge_no"]
            if all(col in df.columns for col in required_cols):
                for _, row in df.iterrows():
                    add_or_update_item(None, row["item_name"].strip().upper(), row["category"].strip().upper(), row["quantity"], row["fridge_no"], st.session_state.username)
                st.success("Items updated or inserted successfully!")
            else:
                st.error(f"Missing required columns: {required_cols}")

    # ---------------- DELETE ALL INVENTORY ----------------
    elif menu == "Delete All Inventory":
        st.title("Delete All Inventory")
        st.warning("This action will delete ALL inventory items permanently.")
        confirm = st.text_input("Type 'DELETE' to confirm")
        if st.button("Delete All Inventory"):
            if confirm == "DELETE":
                delete_all_inventory()
                st.success("All inventory items have been deleted.")
            else:
                st.error("Confirmation text does not match. Inventory not deleted.")


    # ---------------- VIEW PRICING TIERS ----------------
    elif menu == "View Pricing Tiers":
        st.title("View Pricing Tiers")
        data = view_pricing()
        if data.empty:
            st.warning("No pricing found.")
        else:
            paged_df, total_pages = paginate_dataframe(data, page_size=100)
            st.write(f"Showing {len(paged_df)} rows (Page size: 100)")
            st.dataframe(paged_df.style.format({"price_per_unit": "{:,.2f}"}), width="stretch")
            csv_inventory = data.to_csv(index=False)
            st.download_button("Download Pricing Tiers CSV", data=csv_inventory, file_name="Pricing_tiers.csv", mime="text/csv")

    # ---------------- FILE UPLOAD (PRICING) ----------------
    elif menu == "File Upload (Pricing)":
        st.title("File Upload (Pricing)")
        uploaded_file = st.file_uploader("Upload Pricing CSV or Excel file", type=["csv", "xlsx", "xls"])
        if uploaded_file:
            upload_tiered_pricing(uploaded_file)


    # ---------------- MANAGE PRICING TIERS ----------------
    elif menu == "Manage Pricing Tiers":
        #st.title("Manage Pricing Tiers")
        #st.info("This section should allow adding/updating/deleting pricing tiers with Supabase calls.")
        manage_pricing_tiers()

    # ---------------- VIEW AUDIT LOG ----------------
    elif menu == "View Audit Log":
        st.title("Inventory Audit Log")
        start_date = st.date_input("Start Date")
        end_date = st.date_input("End Date")

        if st.button("Filter"):
            audit_df = view_audit_log(start_date, end_date)
        else:
            audit_df = view_audit_log()

        if audit_df.empty:
            st.warning("No audit records found.")
        else:
            paged_audit, total_pages = paginate_dataframe(audit_df, page_size=20)
            st.write(f"Showing {len(paged_audit)} rows (Page size: 20)")
            st.dataframe(paged_audit)
            csv_audit = audit_df.to_csv(index=False)
            st.download_button("Download Audit Log CSV", data=csv_audit, file_name="audit_log.csv", mime="text/csv")

    # ---------------- ADD CUSTOMER ----------------
    elif menu == "Add Customer":
        st.title("Add New Customer")
        name = st.text_input("Customer Name")
        phone = st.text_input("Phone")
        email = st.text_input("Email")
        if email and "@" not in email:
            st.error("Please enter a valid email address.")
        address = st.text_area("Address")
        if st.button("Save Customer"):
            from db_supabase import supabase
            supabase.table("customers").insert({
                "name": name.upper(),
                "phone": phone,
                "email": email.upper(),
                "address": address.upper()
            }).execute()
            st.success(f"Customer '{name}' added successfully!")

    # ---------------- MANAGE CUSTOMERS ----------------
    elif menu == "Manage Customers":
        st.title("Customer List")
        customers_df = view_customers()
        if customers_df.empty:
            st.warning("No customers found.")
        else:
            st.subheader("Current Customers")
            st.dataframe(customers_df[['id','name','phone','email','address']], width='stretch')

        with st.expander("➕ Add / Update Customers", expanded=False):
            if not customers_df.empty:
                customer_options = ["Add New"] + [f"{row['id']} - {row['name']}" for _, row in customers_df.iterrows()]
            else:
                customer_options = ["Add New"]

            selected_customer = st.selectbox("Select Customer", customer_options)
            if selected_customer != "Add New":
                selected_customer_id = int(selected_customer.split(" - ")[0])
                selected_customer_name = selected_customer.split(" - ")[1]
                customer_rows = customers_df[customers_df['name'] == selected_customer_name]
                if not customer_rows.empty:
                    st.info("Existing customer details:")
                    st.dataframe(customer_rows[['id','name','phone','email','address']])
                else:
                    st.warning(f"No records found for customer '{selected_customer_name}'.")
                customer_id = selected_customer_id
                name = st.text_input("Name", value=selected_customer_name)
                phone = st.text_input("Contact No", value=customer_rows.iloc[0]['phone'] if not customer_rows.empty else "")
                email = st.text_input("Email Address", value=customer_rows.iloc[0]['email'] if not customer_rows.empty else "")
                address = st.text_input("Address", value=customer_rows.iloc[0]['address'] if not customer_rows.empty else "")
            else:
                customer_id = None
                name = st.text_input("Name", value="")
                phone = st.text_input("Contact No", value="")
                email = st.text_input("Email Address", value="")
                address = st.text_input("Address", value="")

            if st.button("Save Customer"):
                from db_supabase import supabase
                if customer_id:  # Update existing
                    supabase.table("customers").update({
                        "name": name.strip().upper(),
                        "phone": phone.strip(),
                        "email": email.strip().upper(),
                        "address": address.strip().upper()
                    }).eq("id", customer_id).execute()
                    st.success(f"Customer '{name}' updated successfully!")
                else:  # Insert new (omit id, auto-generated)
                    supabase.table("customers").insert({
                        "name": name.strip().upper(),
                        "phone": phone.strip(),
                        "email": email.strip().upper(),
                        "address": address.strip().upper()
                    }).execute()
                    st.success(f"Customer '{name}' added successfully!")
                st.rerun()

        with st.expander("🗑️ Delete a Customer", expanded=False):
            if customers_df.empty:
                st.warning("No customers to delete.")
            else:
                customers_df['label'] = customers_df.apply(lambda row: f"{row['id']} - {row['name']}", axis=1)
                selected_label = st.selectbox("Select Customer to Delete", customers_df['label'])
                customer_id = int(selected_label.split(" - ")[0])
                if st.button("Delete Customer"):
                    from db_supabase import supabase
                    supabase.table("customers").delete().eq("id", customer_id).execute()
                    st.success(f"Customer with ID {customer_id} deleted successfully!")
                    st.rerun()

    # ---------------- DELETE ALL CUSTOMERS ----------------
    elif menu == "Delete All Customers":
        st.title("Delete All Customers")
        st.warning("This action will delete ALL customers permanently.")
        confirm = st.text_input("Type 'DELETE' to confirm")
        if st.button("Delete All Customers"):
            if confirm == "DELETE":
                delete_all_customers()
                st.success("All customers have been deleted.")
            else:
                st.error("Confirmation text does not match. Customers not deleted.")

    # ---------------- VIEW SALES FOR A CUSTOMER ----------------
    elif menu == "View Sale for a Customer":
        st.title("View Sales for a Customer")
        customers_df = view_customers()
        if customers_df.empty:
            st.warning("No customers found.")
        else:
            customer_label = st.selectbox(
                "Select Customer",
                customers_df.apply(lambda row: f"{row['id']} - {row['name']}", axis=1)
            )
            customer_id = int(customer_label.split(" - ")[0])
            sales_df = view_sales_by_customers(customer_id)
            if sales_df.empty:
                st.warning("No sales records found for this customer.")
            else:
                paged_sales, total_pages = paginate_dataframe(sales_df, page_size=20)
                st.write(f"Showing {len(paged_sales)} rows (Page size: 20)")
                styled_sales = paged_sales.style.format({
                    "total_sale": "{:,.2f}",
                    "selling_price": "{:,.2f}",
                    "cost": "{:,.2f}",
                    "profit": "{:,.2f}"
                })
                st.dataframe(styled_sales, width='stretch')
                csv_sales = sales_df.to_csv(index=False)
                st.download_button("Download Sales CSV", data=csv_sales, file_name="sales_customer.csv", mime="text/csv")

   # ---------------- GENERATE PURCHASE ORDER ----------------
    elif menu == "Generate Purchase Order":
        st.title("Generate Purchase Order (PO)")
        customers_df = view_customers()
        if customers_df.empty:
            st.warning("No customers found.")
        else:
            customer_label = st.selectbox(
                "Select Customer",
                customers_df.apply(lambda row: f"{row['id']} - {row['name']}", axis=1)
            )
            customer_id = int(customer_label.split(" - ")[0])
            sales_df = view_sales_by_customers(customer_id)
            if sales_df.empty:
                st.warning("No sales records found for this customer.")
            else:
                order_dates = sales_df['date'].unique()
                order_date = st.selectbox("Select Order Date", order_dates)
                if isinstance(order_date, date):
                    order_date_sql = order_date.strftime("%Y-%m-%d")
                else:
                    order_date_sql = str(order_date)

                pickup_date = st.date_input("Pickup Date")
                pickup_date_sql = pickup_date.strftime("%Y-%m-%d")

                if st.button("Generate PO"):
                    from fpdf import FPDF
                    from db_supabase import get_po_sequence, get_customer

                    # --- Generate PO Number ---
                    seq = get_po_sequence(order_date_sql)
                    po_number = f"PO-{order_date_sql.replace('-', '')}-{seq:03d}"

                    # --- Vendor Info ---
                    vendor = {
                        "name": "KPrime Food Solutions",
                        "address": "Blk 3 Lot 5 West Wing Villas, North Belton QC",
                        "phone": "+63 995 744 9953",
                        "email": "kprimefoodinc@gmail.com"
                    }

                    # --- Buyer Info ---
                    customer = get_customer(customer_id)
                    buyer = {
                        "name": customer.get("name", ""),
                        "address": customer.get("address", ""),
                        "phone": customer.get("phone", ""),
                        "email": customer.get("email", "")
                    }
                    safe_name = buyer["name"].replace(" ", "_").replace("/", "_")
                    filename = f"PO_{order_date_sql.replace('-', '')}_{safe_name}.pdf"

                    # --- Build PDF ---
                    pdf = FPDF()
                    pdf.add_page()
                    pdf.image("KPrime.jpg", x=10, y=8, w=30)

                    pdf.set_font("Arial", 'B', 14)
                    pdf.cell(0, 10, vendor["name"], ln=True, align="C")
                    pdf.set_font("Arial", size=10)
                    pdf.multi_cell(0, 5, f"{vendor['address']}\nPhone: {vendor['phone']}\nEmail: {vendor['email']}", align="C")
                    pdf.ln(10)

                    pdf.set_font("Arial", 'B', 12)
                    pdf.cell(0, 10, "Purchase Order", ln=True, align="C")
                    pdf.set_font("Arial", size=10)
                    pdf.cell(0, 10, f"PO Number: {po_number}", ln=True)
                    pdf.cell(0, 10, f"Order Date: {order_date_sql}", ln=True)
                    #pdf.cell(0, 10, f"Pickup Date: {pickup_date_sql}", ln=True)
                    pdf.ln(10)

                    # Table header
                    pdf.set_font("Arial", 'B', 10)
                    pdf.cell(20, 10, "No.", 1, align="C")
                    pdf.cell(80, 10, "Description", 1, align="L")
                    pdf.cell(30, 10, "Qty", 1, align="C")
                    pdf.cell(30, 10, "Unit Price", 1, align="R")
                    pdf.cell(30, 10, "Total", 1, align="R")
                    pdf.ln()

                    # Table rows
                    pdf.set_font("Arial", size=10)
                    subtotal = 0
                    for idx, row in sales_df[sales_df['date'] == order_date].iterrows():
                        total = row["quantity"] * row["selling_price"]
                        subtotal += total
                        pdf.cell(20, 10, str(idx+1), 1, align="C")
                        pdf.cell(80, 10, str(row.get("item_name", "")), 1, align="L")
                        pdf.cell(30, 10, str(row.get("quantity", "")), 1, align="C")
                        pdf.cell(30, 10, f"{row.get('selling_price', 0):,.2f}", 1, align="R")
                        pdf.cell(30, 10, f"{total:,.2f}", 1, align="R")
                        pdf.ln()

                    pdf.ln(5)
                    pdf.cell(0, 10, f"Subtotal: PHP {subtotal:,.2f}", ln=True, align="R")
                    pdf.cell(0, 10, "GST: PHP 0.00 (No GST)", ln=True, align="R")
                    pdf.cell(0, 10, f"Total Amount: PHP {subtotal:,.2f}", ln=True, align="R")
                    pdf.ln(10)

                    pdf.cell(0, 10, f"Pickup Date: {pickup_date_sql}", ln=True)
                    pdf.ln(20)
                    pdf.cell(0, 10, "Authorized By: ____________________", ln=True)

                    pdf_bytes = bytes(pdf.output(dest="S"))
                    st.download_button(
                        "Download PO PDF",
                        data=pdf_bytes,
                        file_name=filename,
                        mime="application/pdf"
                    )

    # ---------------- RECORD SALE ----------------
    elif menu == "Record Sale":
        st.title("Record Sale")
        items_df = view_items()
        customers_df = view_customers()
        if items_df.empty:
            st.warning("No items available for sale.")
        elif customers_df.empty:
            st.warning("No customers available. Please add a customer first.")
        else:
            items_df["display"] = items_df.apply(lambda row: f"{row['item_id']} - {row['item_name']}", axis=1)
            item_display = st.selectbox("Select Item", ["Select item"] + items_df["display"].tolist())
            selected_item_id, selected_item_name = None, None
            if item_display != "Select item":
                selected_item_id = int(item_display.split(" - ")[0])
                selected_item_name = item_display.split(" - ")[1]
            customer_label = st.selectbox(
                "Select Customer",
                ["Select customer"] + customers_df.apply(lambda row: f"{row['id']} - {row['name']}", axis=1).tolist()
            )
            if customer_label != "Select customer":
                customer_id = int(customer_label.split(" - ")[0])
                customer_name = customer_label.split(" - ")[1]
                st.success(f"Selected customer: ID={customer_id}, Name={customer_name}")
                quantity = st.number_input("Quantity Sold", min_value=1)
                if st.button("Record Sale"):
                    msg = record_sale(selected_item_id, quantity, st.session_state.username, customer_id)
                    st.success(msg)

    # ---------------- PROFIT/LOSS REPORT ----------------
    elif menu == "Profit/Loss Report":
        st.title("Profit/Loss Report")
        sales_df = view_sales()
        if sales_df.empty:
            st.warning("No sales data available.")
        else:
            total_sales = sales_df['total_sale'].sum()
            total_cost = sales_df['cost'].sum()
            total_profit = sales_df['profit'].sum()
            st.metric("Total Sales", f"${total_sales:,.2f}")
            st.metric("Total Cost", f"${total_cost:,.2f}")
            st.metric("Total Profit", f"${total_profit:,.2f}")
            paged_sales, total_pages = paginate_dataframe(sales_df, page_size=20)
            st.write(f"Showing {len(paged_sales)} rows (Page size: 20)")
            st.dataframe(paged_sales)
            csv_sales = sales_df.to_csv(index=False)
            st.download_button("Download Sales CSV", data=csv_sales, file_name="sales.csv", mime="text/csv")

    # ---------------- CUSTOMER SOA ----------------
    elif menu == "Customer Statement of Account":
        st.title("Customer Statement of Account")
        customers_df = view_customers()
        if customers_df.empty:
            st.warning("No customers found.")
        else:
            customer_label = st.selectbox(
                "Select Customer",
                customers_df.apply(lambda row: f"{row['id']} - {row['name']}", axis=1)
            )
            customer_id = int(customer_label.split(" - ")[0])
            customer_name = customer_label.split(" - ")[1]

            today = date.today()
            start_of_month = today.replace(day=1)
            last_day = calendar.monthrange(today.year, today.month)[1]
            end_of_month = today.replace(day=last_day)

            start_date = st.date_input("Start Date", value=start_of_month)
            end_date = st.date_input("End Date", value=end_of_month)

            # Supabase query for sales by customer and date
            from db_supabase import supabase
            query = supabase.table("sales").select("*").eq("customer_id", customer_id)
            query = query.gte("date", str(start_date)).lte("date", str(end_date))
            res = query.execute()
            sales_customer = pd.DataFrame(res.data)

            if sales_customer.empty:
                st.warning("No sales records found for this customer in the selected period.")
            else:
                st.subheader("Sales Records of Selected Customer")
                paged_sales_customer, total_pages = paginate_dataframe(sales_customer, page_size=20)
                st.write(f"Showing {len(paged_sales_customer)} rows (Page size: 20)")
                styled_sales = paged_sales_customer.style.format({
                    "selling_price": "{:,.2f}",
                    "total_sale": "{:,.2f}",
                    "cost": "{:,.2f}",
                    "profit": "{:,.2f}"
                })
                st.dataframe(styled_sales, width='stretch')
                csv_sales = sales_customer.to_csv(index=False)
                st.download_button("Download Sales CSV", data=csv_sales, file_name="sales_customer.csv", mime="text/csv")

                if st.button("Generate SOA"):
                    from fpdf import FPDF

                    filename = f"SOA_{customer_id}_{start_date}_{end_date}.pdf"
                    pdf = FPDF()
                    pdf.add_page()

                    # --- Logo ---
                    # Place your logo image (PNG/JPG) in your project folder
                    # Adjust x, y, width as needed
                    pdf.image("KPrime.jpg", x=10, y=8, w=30)

                    # --- Company Name & Address ---
                    pdf.set_font("Arial", 'B', 14)
                    pdf.cell(0, 10, "KPrime Food Solutions", ln=True, align="C")

                    pdf.set_font("Arial", size=10)
                    pdf.multi_cell(0, 5, "Blk 3 Lot 5 West Wing Villas, North Belton QC\nPhone: +63 995 744 9953\nEmail: kprimefoodinc@gmail.com", align="C")
                    pdf.ln(10)  # Add some spacing before the document title

                    pdf.set_font("Arial", size=12)

                    # Header
                    pdf.cell(200, 10, txt=f"Statement of Account", ln=True, align="C")
                    pdf.cell(200, 10, txt=f"Customer: {customer_name} (ID: {customer_id})", ln=True)
                    pdf.cell(200, 10, txt=f"Period: {start_date} to {end_date}", ln=True)
                    pdf.ln(10)

                    # Table header
                    pdf.set_font("Arial", 'B', 10)
                    pdf.cell(20, 10, "Date", 1, align="C")
                    pdf.cell(60, 10, "Item", 1, align="L")
                    pdf.cell(20, 10, "Qty", 1, align="C")
                    pdf.cell(40, 10, "Total Sale", 1, align="R")
                    pdf.cell(40, 10, "Profit", 1, align="R")
                    pdf.ln()

                    # Table rows
                    pdf.set_font("Arial", size=10)
                    for _, row in sales_customer.iterrows():
                        pdf.cell(20, 10, str(row.get("date", "")), 1, align="C")
                        pdf.cell(60, 10, str(row.get("item_name", "")), 1, align="L")
                        pdf.cell(20, 10, str(row.get("quantity", "")), 1, align="C")
                        pdf.cell(40, 10, f"{row.get('total_sale', 0):,.2f}", 1, align="R")
                        pdf.cell(40, 10, f"{row.get('profit', 0):,.2f}", 1, align="R")
                        pdf.ln()

                    # ✅ Save PDF properly
                    pdf.output(filename)

                    # ✅ Open in binary mode for download
                    pdf_bytes = bytes(pdf.output(dest="S"))
                    st.download_button("Download SOA PDF", data=pdf_bytes, file_name=filename, mime="application/pdf")
                    #with open(filename, "rb") as f:
                    #    st.download_button("Download SOA PDF", data=f.read(), file_name=filename, mime="application/pdf")

    # ---------------- VIEW PRICE HISTORY ----------------
    elif menu == "View Price History2":
        st.title("Price History")
        from db_supabase import supabase
        res = supabase.table("price_history").select("*").order("timestamp", desc=True).execute()
        df = pd.DataFrame(res.data)
        if df.empty:
            st.warning("No price changes recorded")
        else:
            paged_df, total_pages = paginate_dataframe(df, page_size=20)
            st.write(f"Showing {len(paged_df)} rows (Page size: 20)")
            st.dataframe(paged_df.style.format({
                "old_unit_cost": "{:,.2f}",
                "old_selling_price": "{:,.2f}",
                "new_unit_cost": "{:,.2f}",
                "new_selling_price": "{:,.2f}"
            }))
            csv_data = df.to_csv(index=False)
            st.download_button("Download Price History CSV", data=csv_data, file_name="price_history.csv", mime="text/csv")

    # ---------------- PRICE CHANGE IMPACT REPORT ----------------
    elif menu == "Price Change Impact Report2":
        st.title("Price Change Impact Report")
        items_df = view_items()
        if items_df.empty:
            st.warning("No items available")
        else:
            item = st.selectbox("Select Item", items_df['item_name'])
            from db_supabase import supabase
            history_res = supabase.table("price_history").select("*").eq("item_id", item).order("timestamp").execute()
            history_df = pd.DataFrame(history_res.data)
            if history_df.empty:
                st.warning("No price changes recorded for this item")
            else:
                st.subheader("Price Change Timeline")
                paged_history, total_pages = paginate_dataframe(history_df, page_size=20)
                st.write(f"Showing {len(paged_history)} rows (Page size: 20)")
                st.dataframe(paged_history)
                csv_history = history_df.to_csv(index=False)
                st.download_button("Download Impact Report CSV", data=csv_history, file_name="impact_report.csv", mime="text/csv")
                for idx, row in history_df.iterrows():
                    st.markdown(f"### Change on {row['timestamp']}: {row['old_selling_price']} → {row['new_selling_price']}")