app_name = "abenext_ai"
app_title = "Abenext AI"
app_publisher = "Abenext"
app_description = "AI assistant for ERPNext: bank reconciliation, audit checks, collections, WhatsApp and customer portal"
app_email = "shahrukh@ventureforceglobal.com"
app_license = "mit"

# Apps
# ------------------
required_apps = ["erpnext"]

add_to_apps_screen = [
    {
        "name": "abenext_ai",
        "logo": "/assets/abenext_ai/images/abenext-logo.svg",
        "title": "Abenext AI",
        "route": "/app/abenext-ai",
    }
]

# Desk assets
# ------------------
# Shows a notice to managers when the Abenext subscription needs attention.
app_include_js = "/assets/abenext_ai/js/abenext_license.js"

# Install and update
# ------------------
# Creates module records, settings defaults, Customer fields, Watchdog rules and reminder stages,
# so no site ever needs manual setup.
before_migrate = ["abenext_ai.setup.ensure_module_defs"]
after_migrate = ["abenext_ai.setup.after_migrate"]
after_install = ["abenext_ai.setup.after_install"]

# Bank formats shipped with the app
# ------------------
fixtures = [
    {
        "dt": "AI Bank Format",
        "filters": [
            [
                "name",
                "in",
                [
                    "Meezan Bank - Account Statement",
                    "Easypaisa - Statement of Account",
                    "Faysal Bank - Account Statement",
                    "JazzCash - Account Statement",
                    "Raqami - E-Statement",
                ],
            ]
        ],
    },
]

# Scheduled jobs
# ------------------
scheduler_events = {
    # License status check with the Abenext server
    "hourly": ["abenext_ai.licensing.sync.run"],
    # Audit Watchdog checks
    "daily": ["abenext_ai.watchdog.runner.daily"],
    "cron": {
        # Watchdog morning report (only if switched on in AI Watchdog Settings)
        "0 7 * * *": ["abenext_ai.watchdog.report.morning"],
        # Collections Agent reminders (only if switched on in AI Collections Settings)
        "0 10 * * *": ["abenext_ai.collections_agent.agent.daily"],
    },
}