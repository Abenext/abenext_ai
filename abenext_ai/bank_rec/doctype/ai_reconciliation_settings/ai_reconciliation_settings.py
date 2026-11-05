# Copyright (c) 2026, Abenext. All rights reserved.

import frappe
from frappe import _
from frappe.model.document import Document


class AIReconciliationSettings(Document):
	def validate(self):
		seen = set()
		for row in self.company_accounts:
			if row.company in seen:
				frappe.throw(_("Row {0}: {1} is listed more than once.").format(row.idx, row.company))
			seen.add(row.company)
			for field in ("bank_charges_account", "withholding_tax_account"):
				account = row.get(field)
				if account and frappe.db.get_value("Account", account, "company") != row.company:
					frappe.throw(_("Row {0}: {1} does not belong to {2}.").format(row.idx, account, row.company))


def account_for(company, field="bank_charges_account"):
	"""The account a company uses for missing entries: its own row first, then the default if it belongs to that company."""
	settings = frappe.get_cached_doc("AI Reconciliation Settings")
	for row in settings.company_accounts:
		if row.company == company and row.get(field):
			return row.get(field)
	default = settings.get(field)
	if default and frappe.db.get_value("Account", default, "company") == company:
		return default
	return None
