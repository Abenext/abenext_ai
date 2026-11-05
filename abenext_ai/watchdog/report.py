# Copyright (c) 2026, Abenext. All rights reserved.
"""The Watchdog morning report.

Free: a clear list of open findings, grouped by severity.
With the Audit Watchdog AI license: a short plain-language summary and first actions on top.
Nothing is emailed unless Send Morning Report is ticked in AI Watchdog Settings.
"""

import frappe
from frappe import _
from frappe.utils import escape_html, fmt_money, get_url_to_form

from abenext_ai import ai_client

SEVERITIES = ("High", "Medium", "Low")
COLORS = {"High": "#c0392b", "Medium": "#d35400", "Low": "#b7950b"}
ROLES = ("System Manager", "Accounts Manager")


def _settings():
	return frappe.get_single("AI Watchdog Settings")


def _open_findings(settings):
	allowed = SEVERITIES[: SEVERITIES.index(settings.minimum_severity or "Medium") + 1]
	findings = frappe.get_all(
		"AI Watchdog Finding",
		filters={"status": "Open", "severity": ["in", allowed]},
		fields=["name", "title", "severity", "rule", "details", "amount", "company", "first_seen"],
		order_by="first_seen desc",
		limit=200,
	)
	findings.sort(key=lambda f: SEVERITIES.index(f.severity or "Low"))
	return findings


def _ai_licensed():
	modules = frappe.db.get_single_value("AI Settings", "modules_enabled") or ""
	status = frappe.db.get_single_value("AI Settings", "license_status")
	return "watchdog" in [m.strip() for m in modules.split(",")] and status in ("Active", "Grace")


def build_report():
	"""Return {"count", "html", "ai_used", "note"}; count 0 means nothing to report."""
	settings = _settings()
	findings = _open_findings(settings)
	if not findings:
		return {"count": 0, "html": "<p>%s</p>" % _("No open findings. Everything the Watchdog checks looks fine."),
			"ai_used": False, "note": ""}

	summary, note = None, ""
	if settings.use_ai_summary:
		if _ai_licensed():
			try:
				summary = ai_client.process("watchdog.summary", {"findings": [{
					"severity": f.severity, "rule": f.rule, "title": f.title,
					"details": f.details, "amount": f.amount,
				} for f in findings[:60]]})
			except ai_client.AIServerError as exc:
				note = _("AI summary not available: {0}").format(str(exc))
		else:
			note = _("Add Audit Watchdog AI to your Abenext license for a plain-language summary and first actions.")
	return {"count": len(findings), "html": _html(findings, summary), "ai_used": bool(summary), "note": note}


def _html(findings, summary):
	parts = []
	if summary and summary.get("headline"):
		parts.append("<h3 style='margin:0 0 8px'>%s</h3>" % escape_html(summary["headline"]))
		if summary.get("summary"):
			parts.append("<p>%s</p>" % escape_html(summary["summary"]))
		actions = summary.get("first_actions") or []
		if actions:
			parts.append("<p><b>%s</b></p><ol>" % _("Do these first:"))
			for item in actions:
				f = findings[item["finding"] - 1]
				parts.append("<li>%s <a href='%s'>%s</a></li>" % (
					escape_html(item["action"]), get_url_to_form("AI Watchdog Finding", f.name), _("Open")))
			parts.append("</ol>")
	else:
		parts.append("<h3 style='margin:0 0 8px'>%s</h3>" % _("{0} open finding(s) need attention").format(len(findings)))

	for severity in SEVERITIES:
		group = [f for f in findings if f.severity == severity]
		if not group:
			continue
		parts.append("<h4 style='color:%s;margin:16px 0 4px'>%s (%d)</h4><ul>" % (COLORS[severity], _(severity), len(group)))
		for f in group[:50]:
			amount = " · %s" % fmt_money(f.amount) if f.amount else ""
			parts.append("<li><a href='%s'>%s</a>%s<br><small>%s</small></li>" % (
				get_url_to_form("AI Watchdog Finding", f.name), escape_html(f.title), amount,
				escape_html((f.details or "")[:250])))
		parts.append("</ul>")
	return "".join(parts)


@frappe.whitelist()
def preview_report():
	frappe.only_for(ROLES)
	return build_report()


def morning():
	"""Scheduled at 7:00. Sends only if Send Morning Report is ticked."""
	settings = _settings()
	if not settings.send_morning_report:
		return
	report = build_report()
	if not report["count"]:
		return
	subject = _("Abenext Watchdog: {0} finding(s) need attention").format(report["count"])
	message = report["html"] + ("<p><small>%s</small></p>" % escape_html(report["note"]) if report["note"] else "")

	users = _manager_users()
	emails = [e.strip() for e in (settings.recipients or "").splitlines() if "@" in e]
	if not emails:
		emails = [e for e in frappe.get_all("User", filters={"name": ["in", users or [""]]}, pluck="email") if e and "@" in e]
	if emails:
		try:
			frappe.sendmail(recipients=emails, subject=subject, message=message)
		except Exception:
			frappe.log_error(title="Abenext Watchdog: morning report email failed")
	for user in users:
		frappe.get_doc({"doctype": "Notification Log", "for_user": user, "type": "Alert", "subject": subject,
			"document_type": "AI Watchdog Settings", "document_name": "AI Watchdog Settings"}).insert(ignore_permissions=True)
	frappe.db.commit()


def _manager_users():
	users = set(frappe.get_all("Has Role", filters={"role": ["in", ROLES], "parenttype": "User"}, pluck="parent"))
	users.discard("Guest")
	return frappe.get_all("User", filters={"name": ["in", list(users) or [""]], "enabled": 1, "user_type": "System User"}, pluck="name")
