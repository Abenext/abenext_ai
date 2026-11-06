# Copyright (c) 2026, Abenext. All rights reserved.
"""Collections Agent: polite, escalating reminders for overdue invoices.

Free: stages, templates, test mode, logging, invoice PDFs.
With the Collections Agent tool on the Abenext license: the AI writes the wording around the
invoice table, in the customer's language. Amounts and invoice numbers always come from ERPNext.
"""

import html
import re
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import cint, escape_html, flt, fmt_money, formatdate, getdate, nowdate

from abenext_ai import ai_client

ROLES = ("System Manager", "Accounts Manager")


def _settings():
	return frappe.get_single("AI Collections Settings")


def daily():
	settings = _settings()
	if settings.enabled:
		run(settings, send=True)


@frappe.whitelist()
def preview():
	frappe.only_for(ROLES)
	return run(_settings(), send=False)


@frappe.whitelist()
def send_now():
	frappe.only_for(ROLES)
	settings = _settings()
	if settings.test_mode and not settings.test_recipient:
		frappe.throw(_("Set a Test Recipient, or turn Test Mode off."))
	results = run(settings, send=True)
	sent = sum(1 for r in results if r.get("status") in ("Sent", "Test Sent"))
	skipped = sum(1 for r in results if r.get("status") == "Skipped")
	return _("{0} reminder(s) sent, {1} skipped. See AI Collection Log.").format(sent, skipped)


def run(settings, send):
	"""Build today's reminders; send and log them if send is True. Returns one dict per customer group."""
	stages = sorted(settings.stages, key=lambda s: s.days_overdue)
	if not stages:
		return []
	results = []
	for group in _overdue_groups(settings):
		stage = None
		for s in stages:
			if group["oldest_days"] >= s.days_overdue:
				stage = s
		if not stage:
			continue
		item = {"customer": group["customer"], "stage": stage.stage_name, "total_text": group["total_text"],
			"invoices": ", ".join(i.name for i in group["invoices"])}

		if _already_sent(group, stage):
			continue
		recipient = _recipient(group["customer_doc"])
		if not recipient:
			item.update(status="Skipped", note=_("No email for this customer. Add a Collections Email or a primary contact email."))
			if send:
				_log(group, stage, item)
			results.append(item)
			continue

		subject, message, ai_written, note = _compose(settings, group, stage)
		item.update(subject=subject, message=message, ai_written=ai_written, note=note)
		to = settings.test_recipient if settings.test_mode else recipient
		item["recipient"] = to + (_(" (test; real recipient {0})").format(recipient) if settings.test_mode else "")
		if send:
			try:
				frappe.sendmail(
					recipients=[to],
					cc=[settings.cc] if settings.cc and not settings.test_mode else None,
					subject=("[TEST] " if settings.test_mode else "") + subject,
					message=message,
					attachments=_attachments(group, stage),
					reference_doctype="Customer",
					reference_name=group["customer"],
				)
				item["status"] = "Test Sent" if settings.test_mode else "Sent"
			except Exception as exc:
				frappe.log_error(title="Abenext Collections: reminder failed")
				item.update(status="Failed", note=str(exc)[:300])
			_log(group, stage, item)
		results.append(item)
	if send:
		frappe.db.commit()
	return results


def _overdue_groups(settings):
	today = getdate(nowdate())
	invoices = frappe.get_all(
		"Sales Invoice",
		filters={"docstatus": 1, "is_return": 0, "outstanding_amount": [">", 0.005], "due_date": ["<", today]},
		fields=["name", "customer", "customer_name", "company", "currency", "grand_total", "outstanding_amount",
			"party_account_currency", "base_grand_total", "posting_date", "due_date"],
		order_by="due_date asc",
		limit=10000,
	)
	groups = defaultdict(list)
	for inv in invoices:
		groups[(inv.customer, inv.company)].append(inv)

	minimum = flt(settings.minimum_amount)
	out = []
	for (customer, company), rows in groups.items():
		doc = frappe.get_cached_doc("Customer", customer)
		if doc.disabled or cint(doc.get("abenext_stop_reminders")):
			continue
		promised = doc.get("abenext_promised_payment_date")
		if promised and getdate(promised) >= today:
			continue
		due_by_currency = defaultdict(float)
		for inv in rows:
			due_by_currency[inv.party_account_currency or inv.currency] += flt(inv.outstanding_amount)
		company_currency = frappe.get_cached_value("Company", company, "default_currency")
		in_company_currency = sum(v for c, v in due_by_currency.items() if c == company_currency)
		if minimum and in_company_currency and in_company_currency < minimum:
			continue
		out.append({
			"customer": customer,
			"customer_doc": doc,
			"customer_name": doc.customer_name or customer,
			"company": company,
			"invoices": rows,
			"oldest_days": (today - getdate(rows[0].due_date)).days,
			"oldest_due": getdate(rows[0].due_date),
			"total_text": ", ".join(fmt_money(v, currency=c) for c, v in sorted(due_by_currency.items())),
		})
	return out


def _already_sent(group, stage):
	"""A stage is sent once per customer until everything is paid (counted from the oldest overdue invoice)."""
	return frappe.db.exists("AI Collection Log", {
		"customer": group["customer"], "company": group["company"], "stage": stage.stage_name,
		"status": ["in", ["Sent", "Test Sent"]], "creation": [">=", group["oldest_due"]],
	})


def _recipient(customer):
	email = (customer.get("abenext_collections_email") or customer.get("email_id") or "").strip()
	if not email and customer.get("customer_primary_contact"):
		email = frappe.db.get_value("Contact", customer.customer_primary_contact, "email_id") or ""
	return email if "@" in email else None


def _invoice_table(group):
	today = getdate(nowdate())
	rows = []
	for inv in group["invoices"]:
		outstanding_currency = inv.party_account_currency or inv.currency
		billed = fmt_money(inv.grand_total, currency=inv.currency)
		rows.append(
			"<tr><td>%s</td><td>%s</td><td>%s</td><td style='text-align:right'>%s</td>"
			"<td style='text-align:right'>%s</td><td style='text-align:right'>%d</td></tr>" % (
				escape_html(inv.name), formatdate(inv.posting_date), formatdate(inv.due_date), billed,
				fmt_money(inv.outstanding_amount, currency=outstanding_currency), (today - getdate(inv.due_date)).days))
	return (
		"<table border='1' cellpadding='6' cellspacing='0' style='border-collapse:collapse'>"
		"<tr><th>%s</th><th>%s</th><th>%s</th><th>%s</th><th>%s</th><th>%s</th></tr>%s</table>" % (
			_("Invoice"), _("Date"), _("Due"), _("Invoice Total"), _("Outstanding"), _("Days Overdue"), "".join(rows))
	)


def _context(group, stage):
	return {
		"customer_name": escape_html(group["customer_name"]),
		"company": escape_html(group["company"]),
		"invoice_table": _invoice_table(group),
		"total_text": group["total_text"],
		"invoice_count": len(group["invoices"]),
		"oldest_days": group["oldest_days"],
		"stage_name": stage.stage_name,
	}


def _ai_licensed():
	modules = frappe.db.get_single_value("AI Settings", "modules_enabled") or ""
	status = frappe.db.get_single_value("AI Settings", "license_status")
	return "collections" in [m.strip() for m in modules.split(",")] and status in ("Active", "Grace")


JINJA_PART = re.compile(r"({{.*?}}|{%.*?%})", re.S)


def _render(template, context):
	"""Render a stage template. The rich-text editor stores > as &gt; (and similar);
	turn those back into characters inside the Jinja parts only, so templates keep working after saving."""
	template = JINJA_PART.sub(lambda m: html.unescape(m.group(0)), template or "")
	return frappe.render_template(template, context)


def _compose(settings, group, stage):
	"""Return (subject, html_message, ai_written, note)."""
	context = _context(group, stage)
	subject = _render(stage.subject, context)
	message = _render(stage.message, context)
	if not settings.use_ai:
		return subject, message, False, ""
	if not _ai_licensed():
		return subject, message, False, _("Template wording (AI wording needs the Collections Agent tool on your license).")
	try:
		draft = ai_client.process("collections.draft", {
			"tone": stage.tone,
			"language": group["customer_doc"].get("abenext_reminder_language") or "English",
			"customer_name": group["customer_name"],
			"company": group["company"],
			"invoice_count": len(group["invoices"]),
			"oldest_days": group["oldest_days"],
			"total_text": group["total_text"],
			"template_subject": subject,
		})
	except ai_client.AIServerError as exc:
		return subject, message, False, _("Template wording (AI not available: {0}).").format(str(exc))
	if not draft.get("body"):
		return subject, message, False, _("Template wording (AI answer not usable).")
	paragraphs = "".join("<p>%s</p>" % escape_html(p) for p in draft["body"].split("\n\n") if p.strip())
	closing = "".join("<p>%s</p>" % escape_html(p) for p in (draft.get("closing") or "").split("\n\n") if p.strip())
	html = paragraphs + context["invoice_table"] + "<p><b>%s %s</b></p>" % (_("Total outstanding:"), context["total_text"]) + closing
	return draft.get("subject") or subject, html, True, ""


def _attachments(group, stage):
	if not stage.attach_invoices:
		return None
	files = []
	for inv in group["invoices"][:10]:
		try:
			files.append(frappe.attach_print("Sales Invoice", inv.name, file_name=inv.name))
		except Exception:
			frappe.log_error(title="Abenext Collections: invoice PDF failed")
	return files or None


def _log(group, stage, item):
	frappe.get_doc({
		"doctype": "AI Collection Log",
		"customer": group["customer"],
		"company": group["company"],
		"stage": stage.stage_name,
		"status": item.get("status"),
		"recipient": (item.get("recipient") or "")[:140],
		"total_text": (item.get("total_text") or "")[:140],
		"invoices": item.get("invoices"),
		"note": item.get("note"),
		"ai_written": 1 if item.get("ai_written") else 0,
		"subject": (item.get("subject") or "")[:140],
		"message": item.get("message"),
	}).insert(ignore_permissions=True)
