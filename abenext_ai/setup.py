# Copyright (c) 2026, Abenext. All rights reserved.
"""Install and update steps, so no client ever needs the console."""

import frappe

SINGLES = ("AI Settings", "AI Reconciliation Settings", "AI Watchdog Settings", "AI Collections Settings")
NO_VALUE = ("Section Break", "Column Break", "Tab Break", "HTML", "Button", "Table", "Table MultiSelect")


def ensure_module_defs():
	"""Create a Module Def for every module in modules.txt (runs before each migrate)."""
	for module in frappe.get_module_list("abenext_ai"):
		if not frappe.db.exists("Module Def", module):
			frappe.get_doc({"doctype": "Module Def", "module_name": module, "app_name": "abenext_ai"}).insert(
				ignore_permissions=True)
	frappe.db.commit()


def ensure_single_defaults():
	"""Settings pages start with their designed defaults instead of empty values.

	Only fields that were never saved are filled; a client's own choices are kept.
	"""
	for doctype in SINGLES:
		if not frappe.db.exists("DocType", doctype):
			continue
		stored = set(frappe.db.sql_list("select field from `tabSingles` where doctype = %s", doctype))
		for df in frappe.get_meta(doctype).fields:
			if df.fieldtype in NO_VALUE or df.fieldname in stored or df.default in (None, ""):
				continue
			frappe.db.set_single_value(doctype, df.fieldname, df.default)


# Fields Abenext AI adds to standard ERPNext doctypes. Prefix abenext_ so they never clash.
CUSTOM_FIELDS = {
	"Customer": [
		{"fieldname": "abenext_collections_section", "fieldtype": "Section Break", "label": "Collections",
			"insert_after": "credit_limits", "collapsible": 1},
		{"fieldname": "abenext_collections_email", "fieldtype": "Data", "options": "Email", "label": "Collections Email",
			"insert_after": "abenext_collections_section",
			"description": "Payment reminders go here. If empty, the customer's primary contact email is used."},
		{"fieldname": "abenext_collections_mobile", "fieldtype": "Data", "options": "Phone", "label": "Collections Mobile",
			"insert_after": "abenext_collections_email"},
		{"fieldname": "abenext_reminder_language", "fieldtype": "Select", "options": "English\nRoman Urdu",
			"default": "English", "label": "Reminder Language", "insert_after": "abenext_collections_mobile"},
		{"fieldname": "abenext_collections_column", "fieldtype": "Column Break", "insert_after": "abenext_reminder_language"},
		{"fieldname": "abenext_stop_reminders", "fieldtype": "Check", "label": "Stop Reminders",
			"insert_after": "abenext_collections_column",
			"description": "Never send this customer automatic payment reminders."},
		{"fieldname": "abenext_promised_payment_date", "fieldtype": "Date", "label": "Promised Payment Date",
			"insert_after": "abenext_stop_reminders",
			"description": "No reminders until after this date."},
	],
}

DEFAULT_STAGES = [
	{"days_overdue": 3, "stage_name": "Friendly reminder", "tone": "Friendly", "attach_invoices": 1,
		"subject": "Payment reminder from {{ company }}",
		"message": "<p>Dear {{ customer_name }},</p>"
		"<p>This is a friendly reminder that the following invoice{{ 's are' if invoice_count > 1 else ' is' }} now past due:</p>"
		"{{ invoice_table }}<p><b>Total outstanding: {{ total_text }}</b></p>"
		"<p>If you have already paid, please ignore this message or reply with the payment details so we can update our records.</p>"
		"<p>Thank you,<br>{{ company }}</p>"},
	{"days_overdue": 15, "stage_name": "Second reminder", "tone": "Firm", "attach_invoices": 1,
		"subject": "Second reminder: overdue invoices from {{ company }}",
		"message": "<p>Dear {{ customer_name }},</p>"
		"<p>Our records show that the following invoice{{ 's remain' if invoice_count > 1 else ' remains' }} unpaid, "
		"the oldest now {{ oldest_days }} days overdue:</p>"
		"{{ invoice_table }}<p><b>Total outstanding: {{ total_text }}</b></p>"
		"<p>Please arrange payment within the next 7 days, or let us know if there is any issue with these invoices.</p>"
		"<p>Regards,<br>{{ company }}</p>"},
	{"days_overdue": 30, "stage_name": "Final notice", "tone": "Final notice", "attach_invoices": 1,
		"subject": "Final notice: overdue payment to {{ company }}",
		"message": "<p>Dear {{ customer_name }},</p>"
		"<p>Despite our earlier reminders, the following invoice{{ 's are' if invoice_count > 1 else ' is' }} still unpaid, "
		"the oldest {{ oldest_days }} days overdue:</p>"
		"{{ invoice_table }}<p><b>Total outstanding: {{ total_text }}</b></p>"
		"<p>Please make the payment within 3 days, or contact us today to agree a payment date.</p>"
		"<p>Regards,<br>{{ company }}</p>"},
]


def ensure_custom_fields():
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields(CUSTOM_FIELDS, update=True)


def ensure_collection_stages():
	"""Give the Collections Agent its three default stages once; never touch stages a client has set."""
	if not frappe.db.exists("DocType", "AI Collections Settings"):
		return
	settings = frappe.get_single("AI Collections Settings")
	if settings.stages:
		return
	for stage in DEFAULT_STAGES:
		settings.append("stages", stage)
	settings.flags.ignore_validate = True
	settings.save(ignore_permissions=True)


def after_install():
	ensure_module_defs()
	ensure_single_defaults()
	ensure_custom_fields()
	ensure_collection_stages()
	from abenext_ai.watchdog.setup import ensure_rules

	ensure_rules()


def after_migrate():
	ensure_single_defaults()
	ensure_custom_fields()
	ensure_collection_stages()
	from abenext_ai.watchdog.setup import ensure_rules

	ensure_rules()
