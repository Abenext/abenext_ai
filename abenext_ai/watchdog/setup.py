# Copyright (c) 2026, Abenext. All rights reserved.

import frappe

from abenext_ai.watchdog.rules import RULES


def ensure_rules():
	"""Create shipped rules that are missing. Existing rules are left as the client set them."""
	for rule in RULES:
		if not frappe.db.exists("AI Watchdog Rule", rule["rule_code"]):
			frappe.get_doc(dict(rule, doctype="AI Watchdog Rule", enabled=1)).insert(ignore_permissions=True)
		else:
			# Only refresh the explanatory text, never the client's settings.
			frappe.db.set_value("AI Watchdog Rule", rule["rule_code"], {
				"description": rule["description"], "threshold_label": rule["threshold_label"],
			}, update_modified=False)
