# Copyright (c) 2026, Abenext. All rights reserved.

import hashlib
import json
from datetime import timedelta

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate

from abenext_ai.bank_rec import extract, match

MODULE = "abenext_ai.bank_rec.doctype.ai_bank_statement.ai_bank_statement"
READY_TO_SUBMIT = ("Ready for Review", "Reconciled")
BATCH_SIZE = 50
BUSY = ("Extracting", "Creating Transactions", "Matching")
REFERENCE_WINDOW_DAYS = 30


class AIBankStatement(Document):
	def validate(self):
		if not self.is_new() and self.has_value_changed("statement_file") and self.status != "Extracting":
			if _has_transactions(self):
				frappe.throw(_("Bank Transactions were already created from this statement, so the file cannot be changed."))
			self.status = "Draft"
			self.set("lines", [])
			self.error_log = ""

	def before_submit(self):
		if self.status not in READY_TO_SUBMIT:
			frappe.throw(_("Process and review the statement before submitting it."))


def _has_transactions(doc):
	return any(row.bank_transaction for row in doc.lines)


def _notify(name):
	frappe.publish_realtime("ai_bank_statement_processed", {"name": name}, doctype="AI Bank Statement", docname=name)


# ---------------------------------------------------------------- reading the PDF


@frappe.whitelist()
def process_statement(name):
	"""Queue reading of the attached PDF. Called from the Process Statement button."""
	doc = frappe.get_doc("AI Bank Statement", name)
	doc.check_permission("write")
	if doc.docstatus != 0:
		frappe.throw(_("Only draft statements can be processed."))
	if doc.status in BUSY:
		frappe.throw(_("This statement is already being processed."))
	if _has_transactions(doc):
		frappe.throw(_("Bank Transactions were already created from this statement, so it cannot be read again."))
	if not doc.statement_file:
		frappe.throw(_("Attach the statement PDF first."))

	doc.db_set({"status": "Extracting", "error_log": ""}, notify=True)
	frappe.enqueue(MODULE + ".run_extraction", queue="long", timeout=1200, name=name, enqueue_after_commit=True)
	return "queued"


def run_extraction(name):
	"""Background job: read the PDF, fill the lines and check every running balance."""
	doc = frappe.get_doc("AI Bank Statement", name)
	try:
		pages = extract.extract_text_pages(_file_path(doc.statement_file))
		bank_format = _pick_format(doc, extract.page_text(pages))
		layout = extract.load_layout(
			bank_format.column_map if bank_format else None,
			bank_format.date_format if bank_format else None,
		)
		result = extract.parse_statement(pages, layout)
		if not result["lines"]:
			raise extract.StatementError(_("No transactions were found in this PDF."))

		doc.set("lines", [])
		for line in result["lines"]:
			doc.append("lines", {
				"date": line["date"],
				"description": line["description"],
				"reference_no": line["reference_no"],
				"debit": flt(line["debit"]),
				"credit": flt(line["credit"]),
				"balance": flt(line["balance"]),
				"balance_ok": 1 if line["balance_ok"] else 0,
				"match_type": "None",
				"line_status": "Pending",
			})

		doc.bank_format = bank_format.name if bank_format else None
		if result["opening_balance"] is not None:
			doc.opening_balance = flt(result["opening_balance"])
		if result["closing_balance"] is not None:
			doc.closing_balance = flt(result["closing_balance"])
		doc.from_date = doc.from_date or result["from_date"]
		doc.to_date = doc.to_date or result["to_date"]

		problems = []
		if result["mismatches"]:
			problems.append(_("{0} line(s) do not agree with the bank's running balance. They are unticked in the Balance OK column.").format(result["mismatches"]))
		if not result["closing_ok"]:
			problems.append(_("The last balance does not equal the closing balance printed on the statement."))
		for item in result["rejected"][:20]:
			problems.append(_("Page {0}, line {1}: {2}").format(item["page"], item["line"], item["reason"]))

		doc.status = "Balance Mismatch" if problems else "Extracted"
		doc.error_log = "\n".join(problems)
		doc.flags.ignore_permissions = True
		doc.save()
	except Exception as exc:
		frappe.db.rollback()
		message = str(exc) if isinstance(exc, extract.StatementError) else _("The statement could not be read. See Error Log for details.")
		frappe.db.set_value("AI Bank Statement", name, {"status": "Failed", "error_log": message})
		frappe.log_error(title="AI Bank Statement processing failed", reference_doctype="AI Bank Statement", reference_name=name)

	frappe.db.commit()
	_notify(name)


def _file_path(file_url):
	file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not file_name:
		raise extract.StatementError(_("The attached file could not be found."))
	path = frappe.get_doc("File", file_name).get_full_path()
	if not path.lower().endswith(".pdf"):
		raise extract.StatementError(_("Attach the statement as a PDF file."))
	return path


def _pick_format(doc, first_page_text):
	"""Choose the enabled AI Bank Format whose header keywords all appear on the first page."""
	text = (first_page_text or "").lower()
	bank = frappe.db.get_value("Bank Account", doc.bank_account, "bank")
	formats = frappe.get_all(
		"AI Bank Format",
		filters={"enabled": 1},
		fields=["name", "bank", "header_keywords", "date_format", "column_map"],
	)
	matches = []
	for bank_format in formats:
		keywords = [k.strip().lower() for k in (bank_format.header_keywords or "").split(",") if k.strip()]
		if keywords and all(k in text for k in keywords):
			matches.append(bank_format)
	matches.sort(key=lambda f: 0 if bank and f.bank == bank else 1)
	return matches[0] if matches else None


# ---------------------------------------------------------------- Bank Transactions


@frappe.whitelist()
def create_bank_transactions(name):
	"""Queue creation of one ERPNext Bank Transaction per statement line."""
	doc = frappe.get_doc("AI Bank Statement", name)
	doc.check_permission("write")
	frappe.has_permission("Bank Transaction", "create", throw=True)
	frappe.has_permission("Bank Transaction", "submit", throw=True)
	if doc.docstatus != 0:
		frappe.throw(_("Only draft statements can create Bank Transactions."))
	if doc.status not in ("Extracted", "Transactions Created"):
		frappe.throw(_("Bank Transactions can only be created after the statement is read and every balance agrees."))
	if all(row.bank_transaction for row in doc.lines):
		frappe.throw(_("Every line already has a Bank Transaction."))

	doc.db_set({"status": "Creating Transactions", "error_log": ""}, notify=True)
	frappe.enqueue(MODULE + ".run_create_transactions", queue="long", timeout=3600, name=name, enqueue_after_commit=True)
	return "queued"


def run_create_transactions(name):
	"""Background job: create and submit Bank Transactions, skipping any that already exist."""
	doc = frappe.get_doc("AI Bank Statement", name)
	created = skipped = 0
	try:
		account = frappe.db.get_value("Bank Account", doc.bank_account, ["account", "company"], as_dict=True)
		if not account or not account.account:
			raise extract.StatementError(_("Bank Account {0} has no linked GL account.").format(doc.bank_account))
		currency = frappe.db.get_value("Account", account.account, "account_currency") or frappe.get_cached_value(
			"Company", account.company, "default_currency"
		)

		occurrences = {}
		for count, row in enumerate(doc.lines, 1):
			# Identical lines can appear more than once (for example a charge, its reversal,
			# then the same charge again). Number them so each keeps its own Bank Transaction.
			base = _line_key(doc.bank_account, row)
			occurrences[base] = occurrences.get(base, 0) + 1
			key = base if occurrences[base] == 1 else "%s-%d" % (base, occurrences[base])
			if row.bank_transaction:
				continue
			existing = frappe.db.get_value(
				"Bank Transaction", {"bank_account": doc.bank_account, "transaction_id": key, "docstatus": 1}, "name"
			)
			if existing:
				frappe.db.set_value("AI Bank Statement Line", row.name, "bank_transaction", existing, update_modified=False)
				skipped += 1
				continue

			transaction = frappe.get_doc({
				"doctype": "Bank Transaction",
				"date": row.date,
				"bank_account": doc.bank_account,
				"company": account.company,
				"currency": currency,
				"deposit": flt(row.credit),
				"withdrawal": flt(row.debit),
				"description": row.description,
				"reference_number": row.reference_no,
				"transaction_id": key,
			})
			transaction.insert()
			transaction.submit()
			frappe.db.set_value("AI Bank Statement Line", row.name, "bank_transaction", transaction.name, update_modified=False)
			created += 1

			if count % BATCH_SIZE == 0:
				frappe.db.commit()

		message = _("{0} Bank Transaction(s) created.").format(created)
		if skipped:
			message += " " + _("{0} already existed and were linked instead.").format(skipped)
		frappe.db.set_value("AI Bank Statement", name, {"status": "Transactions Created", "error_log": message})
	except Exception as exc:
		frappe.db.rollback()
		reason = str(exc) if isinstance(exc, extract.StatementError) else _("Stopped with an error. See Error Log for details.")
		frappe.db.set_value("AI Bank Statement", name, {
			"status": doc.status if doc.status == "Transactions Created" else "Extracted",
			"error_log": _("Bank Transactions were not all created: {0} Click Create Bank Transactions again to continue; lines already done are skipped.").format(reason),
		})
		frappe.log_error(title="AI Bank Statement: Bank Transaction creation failed", reference_doctype="AI Bank Statement", reference_name=name)

	frappe.db.commit()
	_notify(name)


def _line_key(bank_account, row):
	"""A stable id for one statement line, so the same line never becomes two Bank Transactions."""
	raw = "|".join([
		str(bank_account), str(row.date), "%.2f" % flt(row.debit), "%.2f" % flt(row.credit),
		"%.2f" % flt(row.balance), str(row.reference_no or ""),
	])
	return "ABX-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20].upper()


# ---------------------------------------------------------------- matching


@frappe.whitelist()
def find_matches(name):
	"""Queue rule matching of statement lines against Payment Entries and Journal Entries."""
	doc = frappe.get_doc("AI Bank Statement", name)
	doc.check_permission("write")
	if doc.docstatus != 0:
		frappe.throw(_("Only draft statements can be matched."))
	if doc.status not in ("Transactions Created", "Ready for Review"):
		frappe.throw(_("Create Bank Transactions for every line before matching."))
	if not all(row.bank_transaction for row in doc.lines):
		frappe.throw(_("Some lines have no Bank Transaction yet. Create them first."))

	doc.db_set({"status": "Matching", "error_log": ""}, notify=True)
	frappe.enqueue(MODULE + ".run_matching", queue="long", timeout=1800, name=name, enqueue_after_commit=True)
	return "queued"


def run_matching(name):
	"""Background job: match pending lines. Lines a user already accepted or skipped are left alone."""
	doc = frappe.get_doc("AI Bank Statement", name)
	try:
		settings = frappe.get_single("AI Reconciliation Settings")
		gl_account = frappe.db.get_value("Bank Account", doc.bank_account, "account")

		pending = [row for row in doc.lines if (row.line_status or "Pending") == "Pending"]
		for row in pending:
			row.update({"match_type": "None", "matched_voucher_type": None, "matched_voucher": None,
				"matched_vouchers": None, "confidence": 0, "match_reason": None})

		dates = [getdate(row.date) for row in doc.lines]
		window = timedelta(days=REFERENCE_WINDOW_DAYS)
		entries = _load_entries(doc, gl_account, min(dates) - window, max(dates) + window, settings)

		lines = [{
			"key": row.name, "date": getdate(row.date), "deposit": flt(row.credit), "withdrawal": flt(row.debit),
			"reference": row.reference_no, "description": row.description,
		} for row in pending]
		results = match.find_matches(
			lines, entries,
			date_tolerance=settings.date_tolerance_days if settings.date_tolerance_days is not None else 3,
			amount_tolerance=flt(settings.amount_tolerance),
			reference_window=REFERENCE_WINDOW_DAYS,
		)

		by_name = {row.name: row for row in pending}
		for key, found in results.items():
			first = found["entries"][0]
			by_name[key].update({
				"match_type": found["type"],
				"matched_voucher_type": first["voucher_type"],
				"matched_voucher": first["voucher"],
				"matched_vouchers": json.dumps(
					[{"voucher_type": e["voucher_type"], "voucher": e["voucher"], "amount": e["amount"]} for e in found["entries"]]
				) if len(found["entries"]) > 1 else None,
				"confidence": found["confidence"],
				"match_reason": found["reason"],
			})

		exact = sum(1 for r in results.values() if r["type"] == match.EXACT)
		suggested = len(results) - exact
		doc.status = "Ready for Review"
		doc.error_log = _("Exact matches: {0}. Suggested matches: {1}. No match found: {2}.").format(
			exact, suggested, len(pending) - len(results))
		doc.flags.ignore_permissions = True
		doc.save()
	except Exception:
		frappe.db.rollback()
		frappe.db.set_value("AI Bank Statement", name, {
			"status": "Transactions Created",
			"error_log": _("Matching stopped with an error. See Error Log for details."),
		})
		frappe.log_error(title="AI Bank Statement matching failed", reference_doctype="AI Bank Statement", reference_name=name)

	frappe.db.commit()
	_notify(name)


def _load_entries(doc, gl_account, from_date, to_date, settings):
	"""Submitted, uncleared Payment Entries and Journal Entries on this bank's GL account."""
	taken = _taken_elsewhere(doc.name)
	entries = []

	if settings.match_payment_entry:
		payments = frappe.get_all(
			"Payment Entry",
			filters={"docstatus": 1, "company": doc.company, "posting_date": ["between", [from_date, to_date]],
				"clearance_date": ["is", "not set"]},
			or_filters={"paid_from": gl_account, "paid_to": gl_account},
			fields=["name", "posting_date", "paid_from", "paid_to", "paid_amount", "received_amount",
				"reference_no", "party", "party_name"],
		)
		for pe in payments:
			incoming = pe.paid_to == gl_account
			entries.append({
				"id": "Payment Entry:" + pe.name, "voucher_type": "Payment Entry", "voucher": pe.name,
				"date": getdate(pe.posting_date), "direction": "in" if incoming else "out",
				"amount": flt(pe.received_amount if incoming else pe.paid_amount),
				"reference": pe.reference_no, "party": pe.party_name or pe.party,
			})

	if settings.match_journal_entry:
		rows = frappe.db.sql(
			"""
			select je.name, je.posting_date, je.cheque_no, je.pay_to_recd_from,
				jea.debit_in_account_currency as debit, jea.credit_in_account_currency as credit
			from `tabJournal Entry Account` jea
			join `tabJournal Entry` je on je.name = jea.parent
			where je.docstatus = 1 and je.company = %(company)s and jea.account = %(account)s
				and je.posting_date between %(from_date)s and %(to_date)s
				and je.clearance_date is null
			""",
			{"company": doc.company, "account": gl_account, "from_date": from_date, "to_date": to_date},
			as_dict=True,
		)
		for je in rows:
			incoming = flt(je.debit) > 0
			entries.append({
				"id": "Journal Entry:" + je.name, "voucher_type": "Journal Entry", "voucher": je.name,
				"date": getdate(je.posting_date), "direction": "in" if incoming else "out",
				"amount": flt(je.debit if incoming else je.credit),
				"reference": je.cheque_no, "party": je.pay_to_recd_from or "",
			})

	return [e for e in entries if e["id"] not in taken]


def _taken_elsewhere(statement):
	"""Entries already matched on other statements' lines that were not skipped."""
	taken = set()
	rows = frappe.get_all(
		"AI Bank Statement Line",
		filters={"parent": ["!=", statement], "matched_voucher": ["is", "set"], "line_status": ["!=", "Skipped"]},
		fields=["matched_voucher_type", "matched_voucher", "matched_vouchers"],
	)
	for row in rows:
		taken.add("%s:%s" % (row.matched_voucher_type, row.matched_voucher))
		for extra in json.loads(row.matched_vouchers or "[]"):
			taken.add("%s:%s" % (extra["voucher_type"], extra["voucher"]))
	return taken
