# Copyright (c) 2026, Abenext. All rights reserved.
"""Install and update steps, so no client ever needs the console."""

import frappe

SINGLES = ("AI Settings", "AI Reconciliation Settings")
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


def after_install():
	ensure_module_defs()
	ensure_single_defaults()
	from abenext_ai.watchdog.setup import ensure_rules

	ensure_rules()


def after_migrate():
	ensure_single_defaults()
	from abenext_ai.watchdog.setup import ensure_rules

	ensure_rules()
