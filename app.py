"""
Expense Tracker — Web App (V5, multi-user with accounts)
-------------------------------------------------------------
Run this with:
    python3 app.py

Then open your browser to: http://127.0.0.1:5000

Requires two environment variables (set in .env locally, and in
Render's Environment settings for the live version):
    DATABASE_URL — your PostgreSQL connection string
    SECRET_KEY   — any long random string, used to secure login sessions
"""

import os
import csv
import io
import secrets
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, Response, session, flash
import psycopg2
import psycopg2.extras
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY")
if not app.secret_key:
    raise RuntimeError("SECRET_KEY environment variable is required — set it in .env locally and in Render's Environment settings.")

DATABASE_URL = os.environ.get("DATABASE_URL")
MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
MAIL_APP_PASSWORD = os.environ.get("MAIL_APP_PASSWORD")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "").strip().lower()

app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)

BROAD_CATEGORIES = [
    "food", "transport", "shopping", "entertainment",
    "subscriptions", "bills", "health", "travel", "other",
]

CATEGORY_ICONS = {
    "food": "🍔",
    "transport": "🚗",
    "shopping": "🛍️",
    "entertainment": "🎬",
    "subscriptions": "🔁",
    "bills": "🧾",
    "health": "💊",
    "travel": "✈️",
    "other": "📎",
    "uncategorized": "❔",
}

CURRENCIES = {
    "GBP": "£",
    "USD": "$",
    "EUR": "€",
    "INR": "₹",
    "AUD": "A$",
    "CAD": "C$",
    "JPY": "¥",
    "CHF": "CHF ",
    "CNY": "¥",
    "NZD": "NZ$",
}


def get_connection():
    return psycopg2.connect(DATABASE_URL)


def column_exists(cur, table, column):
    cur.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
    """, (table, column))
    return cur.fetchone() is not None


def constraint_exists(cur, name):
    cur.execute("SELECT 1 FROM pg_constraint WHERE conname = %s", (name,))
    return cur.fetchone() is not None


def init_db():
    """Create/upgrade tables as needed. Safe to run on every startup."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    if not column_exists(cur, "users", "reset_token"):
        cur.execute("ALTER TABLE users ADD COLUMN reset_token TEXT")
    if not column_exists(cur, "users", "reset_token_expires"):
        cur.execute("ALTER TABLE users ADD COLUMN reset_token_expires TIMESTAMP")
    if not column_exists(cur, "users", "currency"):
        cur.execute("ALTER TABLE users ADD COLUMN currency TEXT NOT NULL DEFAULT 'GBP'")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id SERIAL PRIMARY KEY,
            date DATE NOT NULL,
            amount NUMERIC(10,2) NOT NULL,
            category TEXT NOT NULL,
            note TEXT
        )
    """)
    if not column_exists(cur, "expenses", "user_id"):
        cur.execute("ALTER TABLE expenses ADD COLUMN user_id INTEGER REFERENCES users(id)")
    if not column_exists(cur, "expenses", "recurring_id"):
        cur.execute("ALTER TABLE expenses ADD COLUMN recurring_id INTEGER")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS budgets (
            category TEXT,
            amount NUMERIC(10,2) NOT NULL
        )
    """)
    if not column_exists(cur, "budgets", "user_id"):
        cur.execute("ALTER TABLE budgets ADD COLUMN user_id INTEGER REFERENCES users(id)")
    if constraint_exists(cur, "budgets_pkey"):
        cur.execute("ALTER TABLE budgets DROP CONSTRAINT budgets_pkey")
    if not constraint_exists(cur, "budgets_user_category_unique"):
        cur.execute("""
            ALTER TABLE budgets
            ADD CONSTRAINT budgets_user_category_unique UNIQUE (user_id, category)
        """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS recurring_expenses (
            id SERIAL PRIMARY KEY,
            category TEXT NOT NULL,
            amount NUMERIC(10,2) NOT NULL,
            note TEXT NOT NULL
        )
    """)
    if not column_exists(cur, "recurring_expenses", "user_id"):
        cur.execute("ALTER TABLE recurring_expenses ADD COLUMN user_id INTEGER REFERENCES users(id)")

    conn.commit()
    cur.close()
    conn.close()


# ----------------------------------------------------------------------
# Auth helpers
# ----------------------------------------------------------------------

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def current_user_id():
    return session["user_id"]


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        if not ADMIN_EMAIL or session.get("email") != ADMIN_EMAIL:
            return redirect(url_for("home"))
        return view(*args, **kwargs)
    return wrapped


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        confirm = request.form["confirm"]

        if password != confirm:
            flash("Passwords don't match.")
            return redirect(url_for("register"))
        if len(password) < 8:
            flash("Password must be at least 8 characters.")
            return redirect(url_for("register"))

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cur.fetchone():
            flash("An account with that email already exists.")
            cur.close()
            conn.close()
            return redirect(url_for("register"))

        password_hash = generate_password_hash(password, method="pbkdf2:sha256")
        cur.execute(
            "INSERT INTO users (email, password_hash) VALUES (%s, %s) RETURNING id",
            (email, password_hash)
        )
        user_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()

        session["user_id"] = user_id
        session["email"] = email
        return redirect(url_for("home"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, password_hash FROM users WHERE email = %s", (email,))
        row = cur.fetchone()
        cur.close()
        conn.close()

        if row and check_password_hash(row[1], password):
            session["user_id"] = row[0]
            session["email"] = email
            session.permanent = bool(request.form.get("remember"))
            return redirect(url_for("home"))

        flash("Incorrect email or password.")
        return redirect(url_for("login"))

    return render_template("login.html")


def send_email(to_address, subject, body):
    if not MAIL_USERNAME or not MAIL_APP_PASSWORD:
        print(f"[email not configured] Would have sent to {to_address}: {subject}")
        return
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = MAIL_USERNAME
    msg["To"] = to_address

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(MAIL_USERNAME, MAIL_APP_PASSWORD)
        server.sendmail(MAIL_USERNAME, [to_address], msg.as_string())


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form["email"].strip().lower()

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        row = cur.fetchone()

        if row:
            token = secrets.token_urlsafe(32)
            expires = datetime.now() + timedelta(hours=1)
            cur.execute(
                "UPDATE users SET reset_token = %s, reset_token_expires = %s WHERE id = %s",
                (token, expires, row[0])
            )
            conn.commit()

            reset_link = url_for("reset_password", token=token, _external=True)
            send_email(
                email,
                "Reset your Ledger password",
                f"Click this link to reset your password (valid for 1 hour):\n\n{reset_link}\n\n"
                f"If you didn't request this, you can safely ignore this email."
            )

        cur.close()
        conn.close()

        # Always show the same message, whether or not the email exists —
        # this avoids revealing which emails have accounts
        flash("If an account exists for that email, a reset link has been sent.")
        return redirect(url_for("login"))

    return render_template("forgot_password.html")


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, reset_token_expires FROM users WHERE reset_token = %s",
        (token,)
    )
    row = cur.fetchone()

    if not row or row[1] < datetime.now():
        cur.close()
        conn.close()
        flash("That reset link is invalid or has expired. Please request a new one.")
        return redirect(url_for("forgot_password"))

    user_id = row[0]

    if request.method == "POST":
        password = request.form["password"]
        confirm = request.form["confirm"]

        if password != confirm:
            flash("Passwords don't match.")
            cur.close()
            conn.close()
            return redirect(url_for("reset_password", token=token))
        if len(password) < 8:
            flash("Password must be at least 8 characters.")
            cur.close()
            conn.close()
            return redirect(url_for("reset_password", token=token))

        password_hash = generate_password_hash(password, method="pbkdf2:sha256")
        cur.execute(
            "UPDATE users SET password_hash = %s, reset_token = NULL, reset_token_expires = NULL WHERE id = %s",
            (password_hash, user_id)
        )
        conn.commit()
        cur.close()
        conn.close()

        flash("Password updated — you can now log in.")
        return redirect(url_for("login"))

    cur.close()
    conn.close()
    return render_template("reset_password.html", token=token)


def get_user_currency(uid):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT currency FROM users WHERE id = %s", (uid,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else "GBP"


@app.route("/admin")
@admin_required
def admin():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM users")
    total_users = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM expenses")
    total_expenses = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM budgets")
    total_budgets = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM recurring_expenses")
    total_recurring = cur.fetchone()[0]

    cur.execute("""
        SELECT u.email, u.created_at, COUNT(e.id) AS expense_count
        FROM users u
        LEFT JOIN expenses e ON e.user_id = u.id
        GROUP BY u.id, u.email, u.created_at
        ORDER BY u.created_at DESC
    """)
    users = [
        {"email": row[0], "created_at": row[1].strftime("%Y-%m-%d"), "expense_count": row[2]}
        for row in cur.fetchall()
    ]

    cur.execute("SELECT COUNT(*) FROM expenses WHERE date >= CURRENT_DATE - INTERVAL '7 days'")
    expenses_last_7_days = cur.fetchone()[0]

    cur.close()
    conn.close()

    return render_template(
        "admin.html",
        total_users=total_users,
        total_expenses=total_expenses,
        total_budgets=total_budgets,
        total_recurring=total_recurring,
        expenses_last_7_days=expenses_last_7_days,
        users=users,
    )


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    uid = current_user_id()
    if request.method == "POST":
        currency = request.form["currency"]
        if currency in CURRENCIES:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("UPDATE users SET currency = %s WHERE id = %s", (currency, uid))
            conn.commit()
            cur.close()
            conn.close()
            flash("Currency updated.")
        return redirect(url_for("settings"))

    return render_template(
        "settings.html",
        currencies=CURRENCIES,
        current_currency=get_user_currency(uid),
        user_email=session.get("email"),
    )


@app.route("/delete-account", methods=["POST"])
@login_required
def delete_account():
    uid = current_user_id()
    password = request.form.get("password", "")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT password_hash FROM users WHERE id = %s", (uid,))
    row = cur.fetchone()

    if not row or not check_password_hash(row[0], password):
        cur.close()
        conn.close()
        flash("Incorrect password — account was not deleted.")
        return redirect(url_for("settings"))

    cur.execute("DELETE FROM expenses WHERE user_id = %s", (uid,))
    cur.execute("DELETE FROM budgets WHERE user_id = %s", (uid,))
    cur.execute("DELETE FROM recurring_expenses WHERE user_id = %s", (uid,))
    cur.execute("DELETE FROM users WHERE id = %s", (uid,))
    conn.commit()
    cur.close()
    conn.close()

    session.clear()
    flash("Your account and all data have been permanently deleted.")
    return redirect(url_for("login"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/claim-legacy-data", methods=["POST"])
@login_required
def claim_legacy_data():
    """One-time: assign any pre-accounts data (user_id IS NULL) to whoever
    clicks this. Meant for the original owner to reclaim their history."""
    uid = current_user_id()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE expenses SET user_id = %s WHERE user_id IS NULL", (uid,))
    cur.execute("UPDATE budgets SET user_id = %s WHERE user_id IS NULL", (uid,))
    cur.execute("UPDATE recurring_expenses SET user_id = %s WHERE user_id IS NULL", (uid,))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for("home"))


def has_unclaimed_data():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM expenses WHERE user_id IS NULL LIMIT 1")
    result = cur.fetchone() is not None
    cur.close()
    conn.close()
    return result


# ----------------------------------------------------------------------
# Data access (all scoped to the current user)
# ----------------------------------------------------------------------

def read_expenses(uid):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id, date, amount, category, note FROM expenses WHERE user_id = %s ORDER BY date DESC, id DESC", (uid,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def add_expense(uid, amount, note, category):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO expenses (date, amount, category, note, user_id) VALUES (%s, %s, %s, %s, %s)",
        (datetime.now().date(), round(float(amount), 2), category, note, uid)
    )
    conn.commit()
    cur.close()
    conn.close()


def get_expense(uid, expense_id):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id, date, amount, category, note FROM expenses WHERE id = %s AND user_id = %s", (expense_id, uid))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def update_expense(uid, expense_id, amount, note, category, date):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE expenses SET amount = %s, note = %s, category = %s, date = %s WHERE id = %s AND user_id = %s",
        (round(float(amount), 2), note, category, date, expense_id, uid)
    )
    conn.commit()
    cur.close()
    conn.close()


def delete_expense(uid, expense_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM expenses WHERE id = %s AND user_id = %s", (expense_id, uid))
    conn.commit()
    cur.close()
    conn.close()


def load_budgets(uid):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT category, amount FROM budgets WHERE user_id = %s", (uid,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {category: float(amount) for category, amount in rows}


def set_budget(uid, category, amount):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO budgets (category, amount, user_id) VALUES (%s, %s, %s)
        ON CONFLICT (user_id, category) DO UPDATE SET amount = EXCLUDED.amount
    """, (category, round(float(amount), 2), uid))
    conn.commit()
    cur.close()
    conn.close()


def get_recurring(uid):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id, category, amount, note FROM recurring_expenses WHERE user_id = %s ORDER BY id", (uid,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def add_recurring(uid, category, amount, note):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO recurring_expenses (category, amount, note, user_id) VALUES (%s, %s, %s, %s)",
        (category, round(float(amount), 2), note, uid)
    )
    conn.commit()
    cur.close()
    conn.close()


def delete_recurring(uid, recurring_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM recurring_expenses WHERE id = %s AND user_id = %s", (recurring_id, uid))
    conn.commit()
    cur.close()
    conn.close()


def ensure_recurring_logged(uid):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, category, amount, note FROM recurring_expenses WHERE user_id = %s", (uid,))
    templates = cur.fetchall()

    for rid, category, amount, note in templates:
        cur.execute("""
            SELECT 1 FROM expenses
            WHERE recurring_id = %s AND user_id = %s
              AND date_trunc('month', date) = date_trunc('month', CURRENT_DATE)
        """, (rid, uid))
        already_logged = cur.fetchone() is not None

        if not already_logged:
            cur.execute(
                "INSERT INTO expenses (date, amount, category, note, recurring_id, user_id) VALUES (%s, %s, %s, %s, %s, %s)",
                (datetime.now().date(), amount, category, note, rid, uid)
            )

    conn.commit()
    cur.close()
    conn.close()


# ----------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------

@app.route("/")
@login_required
def home():
    uid = current_user_id()
    ensure_recurring_logged(uid)
    rows = read_expenses(uid)
    this_month = datetime.now().strftime("%Y-%m")
    filtered = [r for r in rows if r["date"].strftime("%Y-%m") == this_month]

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

    budgets = load_budgets(uid)

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
        recurring=get_recurring(uid),
        last_month_total=last_month_total,
        last_month_label=last_month_date.strftime("%B %Y"),
        month_change_pct=month_change_pct,
        categories=BROAD_CATEGORIES,
        category_icons=CATEGORY_ICONS,
        user_email=session.get("email"),
        show_claim_banner=has_unclaimed_data(),
        currency_symbol=CURRENCIES.get(get_user_currency(uid), "£"),
        is_admin=(ADMIN_EMAIL and session.get("email") == ADMIN_EMAIL),
    )


@app.route("/add", methods=["POST"])
@login_required
def add():
    add_expense(
        current_user_id(),
        amount=request.form["amount"],
        note=request.form["note"],
        category=request.form["category"],
    )
    return redirect(url_for("home"))


@app.route("/edit/<int:expense_id>")
@login_required
def edit_form(expense_id):
    expense = get_expense(current_user_id(), expense_id)
    if expense is None:
        return redirect(url_for("home"))
    expense["date"] = expense["date"].strftime("%Y-%m-%d")
    expense["amount"] = float(expense["amount"])
    return render_template("edit.html", expense=expense, categories=BROAD_CATEGORIES, category_icons=CATEGORY_ICONS, currency_symbol=CURRENCIES.get(get_user_currency(current_user_id()), "£"))


@app.route("/update/<int:expense_id>", methods=["POST"])
@login_required
def update(expense_id):
    update_expense(
        current_user_id(), expense_id,
        amount=request.form["amount"],
        note=request.form["note"],
        category=request.form["category"],
        date=request.form["date"],
    )
    return redirect(url_for("home"))


@app.route("/delete/<int:expense_id>", methods=["POST"])
@login_required
def delete(expense_id):
    delete_expense(current_user_id(), expense_id)
    return redirect(url_for("home"))


@app.route("/budget", methods=["POST"])
@login_required
def budget():
    set_budget(current_user_id(), request.form["category"], request.form["amount"])
    return redirect(url_for("home"))


@app.route("/recurring/add", methods=["POST"])
@login_required
def recurring_add():
    add_recurring(
        current_user_id(),
        category=request.form["category"],
        amount=request.form["amount"],
        note=request.form["note"],
    )
    return redirect(url_for("home"))


@app.route("/recurring/delete/<int:recurring_id>", methods=["POST"])
@login_required
def recurring_delete(recurring_id):
    delete_recurring(current_user_id(), recurring_id)
    return redirect(url_for("home"))


@app.route("/export")
@login_required
def export():
    rows = read_expenses(current_user_id())
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["date", "amount", "category", "note"])
    for r in rows:
        writer.writerow([r["date"].strftime("%Y-%m-%d"), r["amount"], r["category"], r["note"]])

    response = Response(output.getvalue(), mimetype="text/csv")
    filename = f"expenses_export_{datetime.now().strftime('%Y-%m-%d')}.csv"
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response


@app.route("/search")
@login_required
def search():
    uid = current_user_id()
    category = request.args.get("category", "")
    keyword = request.args.get("keyword", "").strip()
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    query = "SELECT id, date, amount, category, note FROM expenses WHERE user_id = %s"
    params = [uid]

    if category:
        query += " AND LOWER(category) = LOWER(%s)"
        params.append(category)
    if keyword:
        query += " AND note ILIKE %s"
        params.append(f"%{keyword}%")
    if start_date:
        query += " AND date >= %s"
        params.append(start_date)
    if end_date:
        query += " AND date <= %s"
        params.append(end_date)

    query += " ORDER BY date DESC, id DESC LIMIT 200"

    cur.execute(query, params)
    results = cur.fetchall()
    cur.close()
    conn.close()

    total = sum(float(r["amount"]) for r in results)
    for r in results:
        r["date"] = r["date"].strftime("%Y-%m-%d")
        r["amount"] = float(r["amount"])

    return render_template(
        "search.html",
        results=results,
        total=total,
        categories=BROAD_CATEGORIES,
        category_icons=CATEGORY_ICONS,
        selected_category=category,
        keyword=keyword,
        start_date=start_date,
        end_date=end_date,
        currency_symbol=CURRENCIES.get(get_user_currency(uid), "£"),
    )


@app.route("/year")
@app.route("/year/<int:year>")
@login_required
def year_view(year=None):
    uid = current_user_id()
    if year is None:
        year = datetime.now().year

    rows = read_expenses(uid)
    year_rows = [r for r in rows if r["date"].year == year]

    monthly_totals = [0.0] * 12
    for r in year_rows:
        monthly_totals[r["date"].month - 1] += float(r["amount"])

    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

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
        category_icons=CATEGORY_ICONS,
        avg_month=avg_month,
        busiest_month=busiest_month,
        expense_count=len(year_rows),
        currency_symbol=CURRENCIES.get(get_user_currency(uid), "£"),
    )


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, port=port, host="0.0.0.0")
