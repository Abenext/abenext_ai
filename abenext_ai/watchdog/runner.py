# Copyright (c) 2026, Abenext. All rights reserved.
"""Runs the Watchdog checks and stores the findings."""

import frappe
from frappe import _
from frappe.utils import now_datetime

from abenext_ai.watchdog.checks import CHECKS, SELF_CLOSING

ROLES = ("System Manager", "Accounts Manager")


def daily():
	# The checks are free and run on the client's own server. AI summaries of the
	# findings are a paid feature handled by the Abenext server.
	run_all()


@frappe.whitelist()
def run_now():
	frappe.only_for(ROLES)
	frappe.enqueue("abenext_ai.watchdog.runner.run_all", queue="long", timeout=3600, enqueue_after_commit=True)
	return "queued"


@frappe.whitelist()
def set_status(names, status):
	if status not in ("Open", "Fixed", "Ignored"):
		frappe.throw(_("Unknown status."))
	for name in frappe.parse_json(names) or []:
		doc = frappe.get_doc("AI Watchdog Finding", name)
		doc.check_permission("write")
		doc.status = status
		doc.save()
	return "ok"


def run_all():
	"""Run every enabled rule for every company. Returns the number of new findings."""
	rules = frappe.get_all("AI Watchdog Rule", filters={"enabled": 1}, fields=["name", "rule_name", "severity", "threshold", "lookback_days"])
	new = 0
	for company in frappe.get_all("Company", pluck="name"):
		for rule in rules:
			check = CHECKS.get(rule.name)
			if not check:
				continue
			try:
				found = check(company, rule)
				new += _store(company, rule, found)
			except Exception:
				frappe.db.rollback()
				frappe.log_error(title="Abenext Watchdog: rule %s failed" % rule.name)
			frappe.db.commit()
	return new


def _store(company, rule, findings):
	now = now_datetime()
	seen, new = set(), 0
	for f in findings:
		seen.add(f["key"])
		existing = frappe.db.get_value("AI Watchdog Finding", {"finding_key": f["key"]}, ["name", "status"], as_dict=True)
		if existing:
			values = {"last_seen": now}
			if existing.status == "Fixed" and rule.name in SELF_CLOSING:
				values.update({"status": "Open", "resolved_by": None, "resolved_on": None})
			frappe.db.set_value("AI Watchdog Finding", existing.name, values, update_modified=False)
			continue
		frappe.get_doc({
			"doctype": "AI Watchdog Finding",
			"finding_key": f["key"],
			"title": f["title"][:140],
			"rule": rule.name,
			"severity": rule.severity,
			"status": "Open",
			"company": company,
			"reference_doctype": f.get("reference_doctype"),
			"reference_name": f.get("reference_name"),
			"related_doctype": f.get("related_doctype"),
			"related_name": f.get("related_name"),
			"amount": f.get("amount"),
			"details": f.get("details"),
			"first_seen": now,
			"last_seen": now,
		}).insert(ignore_permissions=True)
		new += 1

	# Any rule: a finding whose document was deleted or cancelled is closed.
	for f in frappe.get_all("AI Watchdog Finding",
		filters={"rule": rule.name, "company": company, "status": "Open", "finding_key": ["not in", list(seen) or [""]]},
		fields=["name", "reference_doctype", "reference_name", "related_doctype", "related_name"]):
		for doctype, name in ((f.reference_doctype, f.reference_name), (f.related_doctype, f.related_name)):
			if doctype and name and frappe.db.get_value(doctype, name, "docstatus") in (None, 2):
				frappe.db.set_value("AI Watchdog Finding", f.name, {
					"status": "Fixed", "resolved_by": "Abenext Watchdog", "resolved_on": now,
					"note": "%s %s was deleted or cancelled." % (doctype, name),
				}, update_modified=False)
				break

	if rule.name in SELF_CLOSING:
		stale = frappe.get_all("AI Watchdog Finding",
			filters={"rule": rule.name, "company": company, "status": "Open", "finding_key": ["not in", list(seen) or [""]]},
			pluck="name")
		for name in stale:
			frappe.db.set_value("AI Watchdog Finding", name, {
				"status": "Fixed", "resolved_by": "Abenext Watchdog", "resolved_on": now,
				"note": "No longer found by the nightly check.",
			}, update_modified=False)
	return new
