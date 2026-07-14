"""
Expense Tracker — Web App (V4, database-backed)
---------------------------------------------------
Run this with:
    python3 app.py

Then open your browser to: http://127.0.0.1:5000

Requires a DATABASE_URL environment variable pointing at a PostgreSQL
database. On Render, this is set in the service's Environment settings.
Locally, it's read from a .env file.
"""

import os
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")

BROAD_CATEGORIES = [
    "food", "transport", "shopping", "entertainment",
    "subscriptions", "bills", "health", "travel", "other",
]


def get_connection():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    """Create tables if they don't already exist. Safe to run every startup."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id SERIAL PRIMARY KEY,
            date DATE NOT NULL,
            amount NUMERIC(10,2) NOT NULL,
            category TEXT NOT NULL,
            note TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS budgets (
            category TEXT PRIMARY KEY,
            amount NUMERIC(10,2) NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS recurring_expenses (
            id SERIAL PRIMARY KEY,
            category TEXT NOT NULL,
            amount NUMERIC(10,2) NOT NULL,
            note TEXT NOT NULL
        )
    """)
    cur.execute("""
        ALTER TABLE expenses ADD COLUMN IF NOT EXISTS recurring_id INTEGER REFERENCES recurring_expenses(id)
    """)
    conn.commit()
    cur.close()
    conn.close()


def read_expenses():
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id, date, amount, category, note FROM expenses ORDER BY date DESC, id DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def add_expense(amount, note, category):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO expenses (date, amount, category, note) VALUES (%s, %s, %s, %s)",
        (datetime.now().date(), round(float(amount), 2), normalize_category(category), note)
    )
    conn.commit()
    cur.close()
    conn.close()


def get_recurring():
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id, category, amount, note FROM recurring_expenses ORDER BY id")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def add_recurring(category, amount, note):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO recurring_expenses (category, amount, note) VALUES (%s, %s, %s)",
        (normalize_category(category), round(float(amount), 2), note)
    )
    conn.commit()
    cur.close()
    conn.close()


def delete_recurring(recurring_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM recurring_expenses WHERE id = %s", (recurring_id,))
    conn.commit()
    cur.close()
    conn.close()


def ensure_recurring_logged():
    """Check every recurring template — if it hasn't been logged this
    calendar month yet, add it now. Safe to call on every page load."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, category, amount, note FROM recurring_expenses")
    templates = cur.fetchall()

    for rid, category, amount, note in templates:
        cur.execute("""
            SELECT 1 FROM expenses
            WHERE recurring_id = %s
              AND date_trunc('month', date) = date_trunc('month', CURRENT_DATE)
        """, (rid,))
        already_logged = cur.fetchone() is not None

        if not already_logged:
            cur.execute(
                "INSERT INTO expenses (date, amount, category, note, recurring_id) VALUES (%s, %s, %s, %s, %s)",
                (datetime.now().date(), amount, category, note, rid)
            )

    conn.commit()
    cur.close()
    conn.close()


def normalize_category(raw):
    return raw.strip().lower()


def get_all_categories():
    """Every category currently in use, pulled from expenses, budgets, and
    recurring templates, deduplicated. No separate table needed — the
    category list is just whatever's actually been used."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT category FROM expenses
        UNION SELECT category FROM budgets
        UNION SELECT category FROM recurring_expenses
        ORDER BY category
    """)
    categories = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return categories


def rename_category(old_name, new_name):
    old_name = normalize_category(old_name)
    new_name = normalize_category(new_name)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE expenses SET category = %s WHERE category = %s", (new_name, old_name))
    cur.execute("UPDATE recurring_expenses SET category = %s WHERE category = %s", (new_name, old_name))
    # Budgets: if the new name already has a budget, keep the new one and drop the old row
    cur.execute("SELECT amount FROM budgets WHERE category = %s", (old_name,))
    old_budget = cur.fetchone()
    if old_budget:
        cur.execute("""
            INSERT INTO budgets (category, amount) VALUES (%s, %s)
            ON CONFLICT (category) DO NOTHING
        """, (new_name, old_budget[0]))
        cur.execute("DELETE FROM budgets WHERE category = %s", (old_name,))
    conn.commit()
    cur.close()
    conn.close()


def delete_category(category):
    """Deletes the budget for this category (if any). Does NOT delete
    expenses that used it — those stay, just under an 'uncategorized'
    label, since deleting someone's spending history would be surprising."""
    category = normalize_category(category)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM budgets WHERE category = %s", (category,))
    cur.execute("UPDATE expenses SET category = 'uncategorized' WHERE category = %s", (category,))
    cur.execute("DELETE FROM recurring_expenses WHERE category = %s", (category,))
    conn.commit()
    cur.close()
    conn.close()


def get_expense(expense_id):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id, date, amount, category, note FROM expenses WHERE id = %s", (expense_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def update_expense(expense_id, amount, note, category, date):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE expenses SET amount = %s, note = %s, category = %s, date = %s WHERE id = %s",
        (round(float(amount), 2), note, normalize_category(category), date, expense_id)
    )
    conn.commit()
    cur.close()
    conn.close()


def delete_expense(expense_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM expenses WHERE id = %s", (expense_id,))
    conn.commit()
    cur.close()
    conn.close()


def load_budgets():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT category, amount FROM budgets")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {category: float(amount) for category, amount in rows}


def set_budget(category, amount):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO budgets (category, amount) VALUES (%s, %s)
        ON CONFLICT (category) DO UPDATE SET amount = EXCLUDED.amount
    """, (normalize_category(category), round(float(amount), 2)))
    conn.commit()
    cur.close()
    conn.close()


@app.route("/year")
@app.route("/year/<int:year>")
def year_view(year=None):
    if year is None:
        year = datetime.now().year

    rows = read_expenses()
    year_rows = [r for r in rows if r["date"].year == year]

    # Monthly totals, Jan through Dec
    monthly_totals = [0.0] * 12
    for r in year_rows:
        monthly_totals[r["date"].month - 1] += float(r["amount"])

    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    # Category totals for the whole year
    totals_by_category = {}
    year_total = 0.0
    for r in year_rows:
        amt = float(r["amount"])
        totals_by_category[r["category"]] = totals_by_category.get(r["category"], 0) + amt
        year_total += amt

    category_data = [
        {"name": cat, "total": total}
        for cat, total in sorted(totals_by_category.items(), key=lambda x: -x[1])
    ]

    avg_month = year_total / 12
    busiest_month_idx = monthly_totals.index(max(monthly_totals)) if year_total > 0 else None
    busiest_month = month_names[busiest_month_idx] if busiest_month_idx is not None else None

    return render_template(
        "year.html",
        year=year,
        month_names=month_names,
        monthly_totals=[round(m, 2) for m in monthly_totals],
        year_total=year_total,
        category_data=category_data,
        avg_month=avg_month,
        busiest_month=busiest_month,
        expense_count=len(year_rows),
    )


@app.route("/")
def home():
    ensure_recurring_logged()
    rows = read_expenses()
    this_month = datetime.now().strftime("%Y-%m")
    filtered = [r for r in rows if r["date"].strftime("%Y-%m") == this_month]

    # Work out last month's key (handles January -> previous December correctly)
    first_of_this_month = datetime.now().replace(day=1)
    last_month_date = first_of_this_month - timedelta(days=1)
    last_month = last_month_date.strftime("%Y-%m")
    last_month_rows = [r for r in rows if r["date"].strftime("%Y-%m") == last_month]
    last_month_total = sum(float(r["amount"]) for r in last_month_rows)

    totals_by_category = {}
    total_all = 0.0
    for row in filtered:
        amt = float(row["amount"])
        totals_by_category[row["category"]] = totals_by_category.get(row["category"], 0) + amt
        total_all += amt

    budgets = load_budgets()

    category_data = []
    for category, total in sorted(totals_by_category.items(), key=lambda x: -x[1]):
        pct_of_spend = (total / total_all * 100) if total_all > 0 else 0
        budget = budgets.get(category)
        over_budget = budget is not None and total > budget
        budget_pct = (total / budget * 100) if budget else None
        category_data.append({
            "name": category, "total": total, "pct_of_spend": pct_of_spend,
            "budget": budget, "over_budget": over_budget, "budget_pct": budget_pct
        })

    recent = filtered[:10]
    for r in recent:
        r["date"] = r["date"].strftime("%Y-%m-%d")
        r["amount"] = float(r["amount"])

    chart_labels = [c["name"] for c in category_data]
    chart_values = [round(c["total"], 2) for c in category_data]

    if last_month_total > 0:
        month_change_pct = ((total_all - last_month_total) / last_month_total) * 100
    else:
        month_change_pct = None

    return render_template(
        "index.html",
        total_all=total_all,
        category_data=category_data,
        recent=recent,
        month_label=datetime.now().strftime("%B %Y"),
        expense_count=len(filtered),
        chart_labels=chart_labels,
        chart_values=chart_values,
        recurring=get_recurring(),
        last_month_total=last_month_total,
        last_month_label=last_month_date.strftime("%B %Y"),
        month_change_pct=month_change_pct,
        categories=BROAD_CATEGORIES,
    )


@app.route("/add", methods=["POST"])
def add():
    add_expense(
        amount=request.form["amount"],
        note=request.form["note"],
        category=request.form["category"],
    )
    return redirect(url_for("home"))


@app.route("/edit/<int:expense_id>")
def edit_form(expense_id):
    expense = get_expense(expense_id)
    if expense is None:
        return redirect(url_for("home"))
    expense["date"] = expense["date"].strftime("%Y-%m-%d")
    expense["amount"] = float(expense["amount"])
    return render_template("edit.html", expense=expense, categories=BROAD_CATEGORIES)


@app.route("/update/<int:expense_id>", methods=["POST"])
def update(expense_id):
    update_expense(
        expense_id,
        amount=request.form["amount"],
        note=request.form["note"],
        category=request.form["category"],
        date=request.form["date"],
    )
    return redirect(url_for("home"))


@app.route("/delete/<int:expense_id>", methods=["POST"])
def delete(expense_id):
    delete_expense(expense_id)
    return redirect(url_for("home"))


@app.route("/category/rename", methods=["POST"])
def category_rename():
    rename_category(request.form["old_name"], request.form["new_name"])
    return redirect(url_for("home"))


@app.route("/category/delete", methods=["POST"])
def category_delete():
    delete_category(request.form["category"])
    return redirect(url_for("home"))


@app.route("/recurring/add", methods=["POST"])
def recurring_add():
    add_recurring(
        category=request.form["category"],
        amount=request.form["amount"],
        note=request.form["note"],
    )
    return redirect(url_for("home"))


@app.route("/recurring/delete/<int:recurring_id>", methods=["POST"])
def recurring_delete(recurring_id):
    delete_recurring(recurring_id)
    return redirect(url_for("home"))


@app.route("/budget", methods=["POST"])
def budget():
    set_budget(request.form["category"], request.form["amount"])
    return redirect(url_for("home"))


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, port=port, host="0.0.0.0")
