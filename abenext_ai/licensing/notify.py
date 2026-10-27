# Copyright (c) 2026, Abenext. All rights reserved.
"""Tell the client's managers when the Abenext license status changes."""

import frappe
from frappe.utils import formatdate

ROLES = ("System Manager", "Accounts Manager")

MESSAGES = {
	"Grace": (
		"Abenext AI: subscription payment overdue",
		"The Abenext AI subscription has ended{until}. AI suggestions will pause soon unless it is renewed. "
		"Your ERPNext and all your data keep working.",
	),
	"Suspended": (
		"Abenext AI: AI suggestions paused",
		"AI suggestions are paused because the Abenext AI subscription is unpaid. Reading statements, "
		"rule matching and reconciliation still work. AI suggestions resume as soon as payment is received.",
	),
	"Active": (
		"Abenext AI: subscription active again",
		"The Abenext AI subscription is active{until}. AI suggestions are working again.",
	),
}


def status_changed(old, new, valid_till=None):
	"""Bell notification and email to managers. Only for changes that matter to them."""
	if new not in ("Grace", "Suspended") and not (new == "Active" and old in ("Grace", "Suspended")):
		return
	subject, text = MESSAGES[new]
	until = (" until " if new == "Active" else " on ") + formatdate(valid_till) if valid_till else ""
	text = text.format(until=until)

	users = _managers()
	for user in users:
		frappe.get_doc({
			"doctype": "Notification Log",
			"for_user": user,
			"type": "Alert",
			"subject": subject,
			"email_content": text,
			"document_type": "AI Settings",
			"document_name": "AI Settings",
		}).insert(ignore_permissions=True)

	emails = [e for e in frappe.get_all("User", filters={"name": ["in", users or [""]]}, pluck="email") if e and "@" in e]
	if emails:
		try:
			frappe.sendmail(recipients=emails, subject=subject, message="<p>%s</p>" % text)
		except Exception:
			frappe.log_error(title="Abenext AI: license notice email failed")


def _managers():
	users = set(frappe.get_all("Has Role", filters={"role": ["in", ROLES], "parenttype": "User"}, pluck="parent"))
	users.discard("Guest")
	return frappe.get_all(
		"User", filters={"name": ["in", list(users) or [""]], "enabled": 1, "user_type": "System User"}, pluck="name"
	)
