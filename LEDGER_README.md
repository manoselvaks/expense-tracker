# Ledger — Personal Finance Tracker

A full-featured personal finance web app for tracking expenses, budgets, and spending trends — deployed live as a web app and wrapped as a native iOS app.

## What it is

Ledger lets users log expenses, set budgets, and see where their money is going through category breakdowns and time-based views. It's a multi-user application with real authentication (not a single-user toy project), and it ships on two platforms from one codebase: the web, and iOS via a native wrapper.

## Features

**Accounts & security**
- Multi-user accounts with secure password hashing
- Login rate-limiting to slow down brute-force attempts
- Password reset via email (Gmail SMTP)

**Expense tracking**
- Category-tagged expenses with icons
- Credit/debit payment method tracking
- Per-user currency support, with each currency's history kept separate
- Recurring expenses that auto-log monthly

**Budgeting & insight**
- Budgets with warnings when spending approaches or exceeds a limit
- Month / week / year views with stacked category charts (Chart.js)
- Search and filter across expense history
- CSV export for external analysis

**Admin**
- Admin panel for user/data oversight

**Platforms**
- Progressive Web App (installable, works offline-friendly)
- Native iOS app via Capacitor + Xcode, built from the same web codebase

## Tech stack

- **Backend:** Python (Flask)
- **Database:** PostgreSQL, hosted on Render
- **Frontend:** HTML/CSS/JavaScript, Chart.js for visualizations
- **Deployment:** Render (paid tier)
- **Mobile:** Capacitor wrapping the PWA into a native iOS shell, built via Xcode

## Live demo

- Web: `<add live URL here>`
- iOS: `<TestFlight link or App Store link, if applicable>`

## Setup

```bash
git clone <repo-url>
cd <repo-name>
pip install -r requirements.txt
# Configure environment variables: DATABASE_URL, SMTP credentials, SECRET_KEY (see .env.example)
flask run
```

To build the iOS app:

```bash
npx cap sync ios
npx cap open ios
```

## Possible next steps

- Shared/family budgets across multiple accounts
- Bank/card sync via an API like Plaid
- Push notifications for budget warnings on iOS
