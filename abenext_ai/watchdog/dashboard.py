# Copyright (c) 2026, Abenext. All rights reserved.
"""Data for the Audit Watchdog dashboard page. Everything shown comes from the findings themselves."""

import frappe
from frappe import _
from frappe.utils import flt, get_url_to_form, pretty_date

from abenext_ai import ai_client

ROLES = ("System Manager", "Accounts Manager")

AREAS = [
	{"key": "payables", "label": "Accounts Payable", "icon": "money-coins-1",
		"rules": ["DUPLICATE_PURCHASE_INVOICE", "DUPLICATE_PAYMENT"]},
	{"key": "receivables", "label": "Accounts Receivable", "icon": "file",
		"rules": ["DUPLICATE_SALES_INVOICE", "CREDIT_LIMIT_EXCEEDED", "SELLING_BELOW_COST"]},
	{"key": "bank", "label": "Bank & Cash", "icon": "accounting",
		"rules": ["NEGATIVE_CASH", "OLD_UNCLEARED_BANK"]},
	{"key": "stock", "label": "Inventory", "icon": "stock",
		"rules": ["NEGATIVE_STOCK", "VALUATION_JUMP", "DUPLICATE_STOCK_ENTRY"]},
	{"key": "controls", "label": "Financial Controls", "icon": "lock",
		"rules": ["UNUSUAL_JOURNAL_ENTRY", "BACKDATED_ENTRY"]},
	{"key": "vendors", "label": "Vendor Risk", "icon": "users",
		"rules": ["SHARED_BANK_ACCOUNT"]},
]

# Why a rule matters and what to do first. Free, shown for every finding.
GUIDANCE = {
	"DUPLICATE_PURCHASE_INVOICE": (
		["The same bill may be paid twice.", "Inflates expenses and supplier balances."],
		["Compare both invoices with the supplier's original bill.", "Check whether either has been paid.",
			"Cancel the duplicate, or add a debit note if it was paid twice."]),
	"DUPLICATE_PAYMENT": (
		["Money may have left the business twice for one obligation.", "Can point to weak approval or fraud."],
		["Check both payments against the bank statement.", "Confirm with the party which invoice each payment covers.",
			"Ask for a refund or adjust the next payment if it was paid twice."]),
	"DUPLICATE_SALES_INVOICE": (
		["The customer may be billed twice.", "Overstates sales and receivables."],
		["Compare both invoices with the delivery or order.", "Cancel or credit the duplicate before the customer pays it."]),
	"CREDIT_LIMIT_EXCEEDED": (
		["The business is carrying more risk on this customer than agreed.", "Late payment here hurts cash flow."],
		["Hold new orders until payment is received.", "Call the customer about the oldest invoices.",
			"Review whether the credit limit is still right."]),
	"SELLING_BELOW_COST": (
		["Each sale loses money.", "May be a wrong price, a wrong cost, or an unapproved discount."],
		["Check the selling price against the price list.", "Check the item's cost for errors.",
			"Confirm who approved the price."]),
	"NEGATIVE_CASH": (
		["Cash cannot really be below zero, so the books are wrong.", "Often a missing receipt or a double payment."],
		["Count the cash and compare with the books.", "Look for receipts not yet entered.", "Look for payments entered twice."]),
	"OLD_UNCLEARED_BANK": (
		["Entries in the books that the bank has not shown.", "Could be unreconciled, or payments that never happened."],
		["Reconcile the bank account with recent statements.", "Investigate entries still unmatched after that."]),
	"NEGATIVE_STOCK": (
		["Stock cannot really be below zero, so stock values and costs are wrong.", "Usually a missing receipt or an issue entered twice."],
		["Check recent receipts and issues for the item.", "Enter the missing receipt, or cancel the duplicate issue."]),
	"VALUATION_JUMP": (
		["A wrong rate distorts stock value and profit.", "May be a typing error or an unusual purchase."],
		["Check the rate on the receipt against the supplier's invoice.", "Correct the receipt if the rate is wrong."]),
	"DUPLICATE_STOCK_ENTRY": (
		["Stock may be moved or consumed twice.", "Distorts stock levels and production costs."],
		["Compare both entries.", "Delete the extra draft, or cancel the extra submitted entry."]),
	"UNUSUAL_JOURNAL_ENTRY": (
		["Large round or out-of-hours manual entries are a common sign of errors or manipulation."],
		["Ask who made the entry and why.", "Check the supporting documents.", "Confirm it was approved."]),
	"BACKDATED_ENTRY": (
		["Entries dated far in the past can change closed periods and reports already shared."],
		["Ask why it was entered late.", "Check that reports for that period are still correct."]),
	"SHARED_BANK_ACCOUNT": (
		["One bank account for two payees is a classic sign of fake suppliers or employees."],
		["Verify each payee's bank details with them directly.", "Check payments made to this account.",
			"Correct the record that is wrong."]),
}


def _area_of(rule):
	for area in AREAS:
		if rule in area["rules"]:
			return area["key"]
	return "controls"


@frappe.whitelist()
def overview(company=None, status="Open"):
	frappe.only_for(ROLES)
	if status not in ("Open", "Fixed", "Ignored"):
		status = "Open"
	filters = {"status": status}
	if company:
		filters["company"] = company
	rows = frappe.get_all(
		"AI Watchdog Finding",
		filters=filters,
		fields=["name", "title", "rule", "severity", "status", "company", "reference_doctype", "reference_name",
			"related_doctype", "related_name", "amount", "details", "first_seen", "last_seen", "note"],
		order_by="first_seen desc",
		limit=500,
	)
	rule_names = dict(frappe.get_all("AI Watchdog Rule", fields=["name", "rule_name"], as_list=True))
	order = {"High": 0, "Medium": 1, "Low": 2}
	rows.sort(key=lambda r: (order.get(r.severity, 3), -(r.first_seen.timestamp() if r.first_seen else 0)))

	areas = [{"key": a["key"], "label": _(a["label"]), "icon": a["icon"], "High": 0, "Medium": 0, "Low": 0} for a in AREAS]
	by_key = {a["key"]: a for a in areas}
	findings = []
	for r in rows:
		area = _area_of(r.rule)
		by_key[area][r.severity or "Low"] = by_key[area].get(r.severity or "Low", 0) + 1
		why, actions = GUIDANCE.get(r.rule, ([], []))
		findings.append(dict(r,
			area=area,
			rule_name=rule_names.get(r.rule) or r.rule,
			reference_url=get_url_to_form(r.reference_doctype, r.reference_name) if r.reference_name else "",
			related_url=get_url_to_form(r.related_doctype, r.related_name) if r.related_name else "",
			why=[_(w) for w in why], actions=[_(a) for a in actions]))

	last_run = frappe.db.sql("select max(last_seen) from `tabAI Watchdog Finding`")[0][0]
	return {
		"areas": areas,
		"findings": findings,
		"totals": {
			"count": len(findings),
			"high": sum(1 for f in findings if f["severity"] == "High"),
			"medium": sum(1 for f in findings if f["severity"] == "Medium"),
			"amount": sum(abs(flt(f["amount"])) for f in findings),
		},
		"last_run": pretty_date(last_run) if last_run else "",
		"companies": frappe.get_all("Company", pluck="name"),
		"ai_available": _ai_licensed(),
		"scheduler_paused": frappe.get_attr("abenext_ai.setup.scheduler_paused")(),
	}


@frappe.whitelist()
def history(name):
	"""Earlier findings of the same rule that were resolved, with their notes."""
	frappe.only_for(ROLES)
	finding = frappe.get_doc("AI Watchdog Finding", name)
	same_document = frappe.db.count("AI Watchdog Finding", {
		"reference_name": finding.reference_name, "name": ["!=", name]}) if finding.reference_name else 0
	resolved = frappe.get_all(
		"AI Watchdog Finding",
		filters={"rule": finding.rule, "status": ["in", ["Fixed", "Ignored"]], "name": ["!=", name]},
		fields=["title", "status", "resolved_on", "note"],
		order_by="resolved_on desc",
		limit=4,
	)
	return {
		"same_document": same_document,
		"resolved_count": frappe.db.count("AI Watchdog Finding", {"rule": finding.rule, "status": ["in", ["Fixed", "Ignored"]]}),
		"resolved": [dict(r, when=pretty_date(r.resolved_on) if r.resolved_on else "") for r in resolved],
	}


def _ai_licensed():
	modules = frappe.db.get_single_value("AI Settings", "modules_enabled") or ""
	status = frappe.db.get_single_value("AI Settings", "license_status")
	return "watchdog" in [m.strip() for m in modules.split(",")] and status in ("Active", "Grace")


@frappe.whitelist()
def explain(name):
	"""AI analysis of one finding (Audit Watchdog AI on the license)."""
	frappe.only_for(ROLES)
	if not _ai_licensed():
		frappe.throw(_("Add Audit Watchdog AI to your Abenext license to explain findings with AI."))
	f = frappe.get_doc("AI Watchdog Finding", name)
	try:
		return ai_client.process("watchdog.explain", {
			"rule": f.rule, "severity": f.severity, "title": f.title, "details": f.details,
			"amount": f.amount, "reference": "%s %s" % (f.reference_doctype or "", f.reference_name or ""),
		})
	except ai_client.AIServerError as exc:
		frappe.throw(str(exc), title=_("AI not available"))
