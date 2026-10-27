# Copyright (c) 2026, Abenext. All rights reserved.
"""Switch on AI suggestions where the setting has never been saved."""

import frappe


def execute():
	saved = frappe.db.sql(
		"select 1 from `tabSingles` where doctype = %s and field = %s",
		("AI Reconciliation Settings", "use_ai_suggestions"),
	)
	if not saved:
		frappe.db.set_single_value("AI Reconciliation Settings", "use_ai_suggestions", 1)
