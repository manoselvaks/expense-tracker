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
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")


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
        (datetime.now().date(), round(float(amount), 2), category, note)
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
    """, (category, round(float(amount), 2)))
    conn.commit()
    cur.close()
    conn.close()


@app.route("/")
def home():
    rows = read_expenses()
    this_month = datetime.now().strftime("%Y-%m")
    filtered = [r for r in rows if r["date"].strftime("%Y-%m") == this_month]

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

    return render_template(
        "index.html",
        total_all=total_all,
        category_data=category_data,
        recent=recent,
        month_label=datetime.now().strftime("%B %Y"),
        expense_count=len(filtered),
        chart_labels=chart_labels,
        chart_values=chart_values,
    )


@app.route("/add", methods=["POST"])
def add():
    add_expense(
        amount=request.form["amount"],
        note=request.form["note"],
        category=request.form["category"],
    )
    return redirect(url_for("home"))


@app.route("/delete/<int:expense_id>", methods=["POST"])
def delete(expense_id):
    delete_expense(expense_id)
    return redirect(url_for("home"))


@app.route("/budget", methods=["POST"])
def budget():
    set_budget(request.form["category"], request.form["amount"])
    return redirect(url_for("home"))


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, port=port, host="0.0.0.0")
