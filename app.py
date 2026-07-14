"""
Expense Tracker — Web App (V3)
--------------------------------
Run this with:
    python3 app.py

Then open your browser to: http://127.0.0.1:5000

This uses the SAME expenses.csv and budgets.json files as tracker_v2.py,
so if you copy this into your ~/expense-tracker folder, all your existing
data carries over automatically.
"""

import csv
import os
import json
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "expenses.csv")
BUDGET_FILE = os.path.join(BASE_DIR, "budgets.json")


def read_expenses():
    if not os.path.isfile(LOG_FILE):
        return []
    with open(LOG_FILE, "r") as f:
        rows = list(csv.DictReader(f))

    # Migrate older files that don't have an "id" column yet
    if rows and "id" not in rows[0]:
        for i, r in enumerate(rows, start=1):
            r["id"] = str(i)
        with open(LOG_FILE, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "date", "amount", "category", "note"])
            for r in rows:
                writer.writerow([r["id"], r["date"], r["amount"], r["category"], r["note"]])

    return rows


def add_expense(amount, note, category):
    file_exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["id", "date", "amount", "category", "note"])
        writer.writerow([next_id(), datetime.now().strftime("%Y-%m-%d"), round(float(amount), 2), category, note])


def next_id():
    rows = read_expenses()
    if not rows:
        return 1
    return max(int(r["id"]) for r in rows) + 1


def delete_expense(expense_id):
    rows = read_expenses()
    remaining = [r for r in rows if r["id"] != str(expense_id)]
    with open(LOG_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "date", "amount", "category", "note"])
        for r in remaining:
            writer.writerow([r["id"], r["date"], r["amount"], r["category"], r["note"]])


def load_budgets():
    if not os.path.isfile(BUDGET_FILE):
        return {}
    with open(BUDGET_FILE, "r") as f:
        return json.load(f)


def save_budgets(budgets):
    with open(BUDGET_FILE, "w") as f:
        json.dump(budgets, f, indent=2)


@app.route("/")
def home():
    rows = read_expenses()
    this_month = datetime.now().strftime("%Y-%m")
    filtered = [r for r in rows if r["date"].startswith(this_month)]

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

    recent = sorted(filtered, key=lambda r: r["date"], reverse=True)[:10]

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


@app.route("/delete/<expense_id>", methods=["POST"])
def delete(expense_id):
    delete_expense(expense_id)
    return redirect(url_for("home"))


@app.route("/add", methods=["POST"])
def add():
    add_expense(
        amount=request.form["amount"],
        note=request.form["note"],
        category=request.form["category"],
    )
    return redirect(url_for("home"))


@app.route("/budget", methods=["POST"])
def budget():
    budgets = load_budgets()
    budgets[request.form["category"]] = round(float(request.form["amount"]), 2)
    save_budgets(budgets)
    return redirect(url_for("home"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, port=port, host="0.0.0.0")
