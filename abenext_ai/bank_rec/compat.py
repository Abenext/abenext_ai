# Copyright (c) 2026, Abenext. All rights reserved.
"""All differences between ERPNext versions live here."""

import json


def reconcile(bank_transaction, vouchers):
	"""Reconcile a Bank Transaction with vouchers using ERPNext's own reconciliation.

	vouchers: [{"payment_doctype": "Payment Entry", "payment_name": "ACC-PAY-..."}, ...]
	ERPNext allocates the amounts and sets the clearance dates.
	"""
	from erpnext.accounts.doctype.bank_reconciliation_tool.bank_reconciliation_tool import reconcile_vouchers

	return reconcile_vouchers(bank_transaction, json.dumps(vouchers))
