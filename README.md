# Abenext AI

AI-assisted bank reconciliation for ERPNext. Upload a bank statement PDF and Abenext AI reads every line, checks every running balance, creates the Bank Transactions, matches them to your Payment Entries and Journal Entries, and reconciles them through ERPNext's own reconciliation, with a person approving every match.

This is the client app. It is installed on each client's ERPNext site and works with the **Abenext Server** app, which holds licensing, billing and all AI processing.

> Open source under the MIT License. See [license.txt](license.txt).
>
> **Free:** statement reading with balance check, Bank Transactions, rule matching, review, reconciliation, and the Audit Watchdog checks.
> **With an Abenext subscription:** AI suggestions for lines the rules cannot match, AI summaries, and the upcoming AI tools. These run on Abenext's server and need a license.

## Features

**Statement reading**
- Reads text-based PDF statements locally on the client's server, using each word's position on the page, so empty debit or credit cells and multi-line descriptions are handled correctly.
- Checks every line: opening balance + credits − debits must equal the bank's running balance, and the last balance must equal the printed closing balance.
- Bank layouts are settings (**AI Bank Format**), not code. Included: Meezan Bank. Other banks are added as formats.

**Bank Transactions**
- One submitted ERPNext Bank Transaction per statement line.
- A stable ID per line prevents duplicates, including identical lines on the same day, such as reversals.

**Matching**
1. **Rules:** exact reference and amount; same amount and date with the party named in the description; several entries for one party that add up to one bank line.
2. **AI suggestions** for what the rules cannot match: abbreviations ("KE" for Karachi Electric), partial names, payments covering several invoices. Every AI proposal is checked on the server (exact amounts, same direction, dates within 7 days, each entry used once) and capped at 90% confidence, so it always waits for a person to accept it.

**Review and reconciliation**
- Accept, skip or change any match; accept everything above a confidence threshold in one click.
- Create draft Journal Entries for unmatched lines such as bank charges, then submit them in one step.
- Reconcile accepted lines with ERPNext's own `reconcile_vouchers`, which links the Bank Transaction and sets clearance dates. The standard Bank Reconciliation Statement report agrees.

**Licensing**
- Each site has a License ID and a signing secret. Every request is signed with HMAC-SHA256; the secret never leaves the site.
- Hourly license check. Managers get a notification and email when the subscription is overdue, paused, or active again.
- If the subscription lapses, only AI suggestions pause. Reading, rule matching and reconciliation keep working, and ERPNext is never locked.

## Requirements

- Frappe and ERPNext **version 15**
- Python package `pdfplumber` in the bench environment
- Outbound HTTPS (port 443) from the client server to the Abenext server
- An outgoing Email Account, for manager emails (bell notifications work without it)

## Installation

```bash
cd ~/frappe-bench
bench get-app https://github.com/Abenext/abenext_ai.git
bench --site <site> install-app abenext_ai
```

That's all for the free features. Modules, rules and settings are set up automatically.

Then in the site:

1. **Bank Account**: for each bank account you will reconcile, tick **Is Company Account** and choose its GL account.
2. **AI Reconciliation Settings**: check the tolerances and set your bank charges account.
3. **For AI features** (optional): enter the Server URL, License ID and Signing Secret from your Abenext subscription in **AI Settings**, then click **Test Connection**. Without a license, everything else keeps working.

## Using it

1. **AI Bank Statement → New**: choose the Bank Account, attach the PDF, save, click **Process Statement**.
2. **Create Bank Transactions**.
3. **Find Matches**.
4. Review: **Accept All Above Threshold**, check the suggestions, accept or change them.
5. **Missing Entries** for bank charges and similar lines.
6. **Reconcile**. When every line is reconciled or skipped, submit the statement.

The customer handbook has the full walkthrough.

## Structure

```
abenext_ai/
  ai_client.py          only file that talks to the Abenext server (signed requests)
  bank_rec/
    extract.py          PDF reading and balance check (no database access)
    match.py            rule matching (no database access)
    compat.py           ERPNext version differences
    doctype/            AI Bank Statement, Line, Format, Reconciliation Settings
  licensing/
    doctype/ai_settings license settings and Test Connection
    sync.py             hourly license check
    notify.py           manager notifications on status change
  patches/              data updates run on migrate
  public/js/            desk-wide license notice
  fixtures/             shipped bank formats
```

## Development rules

- No client-specific code: a client need becomes a setting, or a paid customization in a separate app.
- Never modify standard ERPNext doctypes or core code. Use hooks, own doctypes and fixtures.
- No AI provider keys or prompts in this app; they live on the Abenext server.
- Contributions are welcome through pull requests to `develop`.
- Long work runs in background jobs, and every job writes its outcome to the document.
- Nothing posts to the books without a person's click.
- Branches: `develop` for daily work; `version-15` for releases, tagged `vX.Y.Z`.
- Commit messages describe the change in plain words.
