# Copyright (c) 2026, Abenext. All rights reserved.
"""Regular license check, so status changes reach the client without anyone clicking anything."""

import frappe

from abenext_ai import ai_client


def run():
	settings = frappe.get_single("AI Settings")
	if not (settings.server_url and settings.license_id):
		return
	try:
		ai_client.process("ping")
	except ai_client.AIServerError:
		# A refusal still carries the license status, which ai_client has already stored.
		pass
	frappe.db.commit()


# Older hooks pointed at daily(); keep it working.
daily = run
