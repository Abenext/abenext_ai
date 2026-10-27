# Copyright (c) 2026, Abenext. All rights reserved.
"""One function per rule. Each returns a list of findings for one company.

A finding is a dict with: key, title, details, reference_doctype, reference_name,
and optionally related_doctype, related_name, amount. Checks only read data.
"""

from collections import defaultdict

import frappe
from frappe.utils import add_days, flt, fmt_money, formatdate, getdate, nowdate


def _since(rule):
	return add_days(nowdate(), -int(rule.lookback_days or 30))


def duplicate_purchase_invoice(company, rule):
	days = int(rule.threshold or 3)
	rows = frappe.db.sql(
		"""
		select a.name as first, b.name as second, a.supplier, a.bill_no, b.bill_no as second_bill,
			a.grand_total, a.posting_date
		from `tabPurchase Invoice` a
		join `tabPurchase Invoice` b
			on b.supplier = a.supplier and b.company = a.company and b.name > a.name
			and b.docstatus = 1 and b.is_return = 0
		where a.docstatus = 1 and a.is_return = 0 and a.company = %(company)s
			and a.posting_date >= %(since)s
			and (
				(ifnull(a.bill_no, '') != '' and a.bill_no = b.bill_no)
				or (a.grand_total = b.grand_total and abs(datediff(a.posting_date, b.posting_date)) <= %(days)s)
			)
		limit 200
		""",
		{"company": company, "since": _since(rule), "days": days},
		as_dict=True,
	)
	findings = []
	for r in rows:
		same_bill = r.bill_no and r.bill_no == r.second_bill
		reason = "the same bill number %s" % r.bill_no if same_bill else "the same amount within %d days" % days
		findings.append({
			"key": "DUPLICATE_PURCHASE_INVOICE:%s:%s" % (r.first, r.second),
			"title": "Possible duplicate invoice from %s" % r.supplier,
			"details": "%s and %s are both from %s with %s (%s)." % (
				r.first, r.second, r.supplier, reason, fmt_money(r.grand_total)),
			"reference_doctype": "Purchase Invoice", "reference_name": r.second,
			"related_doctype": "Purchase Invoice", "related_name": r.first,
			"amount": r.grand_total,
		})
	return findings


def negative_stock(company, rule):
	rows = frappe.db.sql(
		"""
		select bin.item_code, bin.warehouse, bin.actual_qty, bin.stock_uom
		from `tabBin` bin
		join `tabWarehouse` wh on wh.name = bin.warehouse
		where bin.actual_qty < 0 and wh.company = %(company)s
		limit 500
		""",
		{"company": company},
		as_dict=True,
	)
	return [{
		"key": "NEGATIVE_STOCK:%s:%s" % (r.item_code, r.warehouse),
		"title": "Negative stock: %s in %s" % (r.item_code, r.warehouse),
		"details": "The system shows %s %s of %s in %s. Stock cannot really be below zero; "
		"a receipt is probably missing or an issue was entered twice." % (
			flt(r.actual_qty, 3), r.stock_uom or "", r.item_code, r.warehouse),
		"reference_doctype": "Item", "reference_name": r.item_code,
	} for r in rows]


def unusual_journal_entry(company, rule):
	findings = []
	minimum = flt(rule.threshold) or 500000
	large = frappe.db.sql(
		"""
		select distinct je.name, je.total_debit, je.posting_date, je.voucher_type
		from `tabJournal Entry` je
		join `tabJournal Entry Account` jea on jea.parent = je.name
		join `tabAccount` acc on acc.name = jea.account
		where je.docstatus = 1 and je.company = %(company)s and je.posting_date >= %(since)s
			and je.total_debit >= %(minimum)s and mod(je.total_debit, 10000) = 0
			and ifnull(je.cheque_no, '') = '' and acc.account_type in ('Cash', 'Bank')
		limit 200
		""",
		{"company": company, "since": _since(rule), "minimum": minimum},
		as_dict=True,
	)
	for r in large:
		findings.append({
			"key": "UNUSUAL_JOURNAL_ENTRY:ROUND:%s" % r.name,
			"title": "Large round Journal Entry to cash or bank: %s" % fmt_money(r.total_debit),
			"details": "%s on %s moves %s through a cash or bank account with no reference number." % (
				r.name, formatdate(r.posting_date), fmt_money(r.total_debit)),
			"reference_doctype": "Journal Entry", "reference_name": r.name, "amount": r.total_debit,
		})

	holidays = set()
	holiday_list = frappe.get_cached_value("Company", company, "default_holiday_list")
	if holiday_list:
		holidays = {getdate(d) for d in frappe.get_all("Holiday", filters={"parent": holiday_list}, pluck="holiday_date")}
	# Bank Entries carry the bank's date, which can fall on any day, so only manual entries are checked.
	manual = frappe.get_all(
		"Journal Entry",
		filters={"docstatus": 1, "company": company, "posting_date": [">=", _since(rule)],
			"voucher_type": ["in", ["Journal Entry", "Cash Entry"]]},
		fields=["name", "posting_date", "total_debit", "voucher_type"],
		limit=1000,
	)
	for r in manual:
		day = getdate(r.posting_date)
		if day.weekday() == 6 or day in holidays:
			findings.append({
				"key": "UNUSUAL_JOURNAL_ENTRY:DAY:%s" % r.name,
				"title": "%s posted on a %s" % (r.voucher_type, "holiday" if day in holidays else "Sunday"),
				"details": "%s is dated %s, which is a %s. Check that the date is right." % (
					r.name, formatdate(day), "holiday" if day in holidays else "Sunday"),
				"reference_doctype": "Journal Entry", "reference_name": r.name, "amount": r.total_debit,
			})
	return findings


def valuation_jump(company, rule):
	percent = flt(rule.threshold) or 50
	rows = frappe.db.sql(
		"""
		select sle.item_code, sle.warehouse, sle.voucher_type, sle.voucher_no, sle.posting_date,
			sle.incoming_rate,
			(
				select avg(p.incoming_rate) from `tabStock Ledger Entry` p
				where p.item_code = sle.item_code and p.warehouse = sle.warehouse
					and p.is_cancelled = 0 and p.actual_qty > 0 and p.incoming_rate > 0
					and p.posting_date < sle.posting_date
					and p.posting_date >= date_sub(sle.posting_date, interval 90 day)
			) as usual_rate
		from `tabStock Ledger Entry` sle
		where sle.company = %(company)s and sle.is_cancelled = 0 and sle.actual_qty > 0
			and sle.incoming_rate > 0 and sle.posting_date >= %(since)s
		limit 2000
		""",
		{"company": company, "since": _since(rule)},
		as_dict=True,
	)
	findings = []
	for r in rows:
		usual = flt(r.usual_rate)
		if not usual:
			continue
		change = (flt(r.incoming_rate) - usual) / usual * 100
		if abs(change) <= percent:
			continue
		findings.append({
			"key": "VALUATION_JUMP:%s:%s:%s" % (r.voucher_no, r.item_code, r.warehouse),
			"title": "Rate of %s is %d%% %s usual" % (r.item_code, abs(change), "above" if change > 0 else "below"),
			"details": "%s on %s received %s into %s at %s each; the average over the previous 90 days was %s." % (
				r.voucher_no, formatdate(r.posting_date), r.item_code, r.warehouse,
				fmt_money(r.incoming_rate), fmt_money(usual)),
			"reference_doctype": r.voucher_type, "reference_name": r.voucher_no,
		})
	return findings


def duplicate_stock_entry(company, rule):
	# Drafts are included: a duplicate draft is best caught before anyone submits it.
	entries = frappe.get_all(
		"Stock Entry",
		filters={"docstatus": ["<", 2], "company": company, "posting_date": [">=", _since(rule)]},
		fields=["name", "stock_entry_type", "posting_date", "docstatus"],
		limit=5000,
	)
	if not entries:
		return []
	by_name = {e.name: e for e in entries}
	items = defaultdict(list)
	for d in frappe.get_all(
		"Stock Entry Detail",
		filters={"parent": ["in", list(by_name)]},
		fields=["parent", "item_code", "qty", "s_warehouse", "t_warehouse"],
		limit=50000,
	):
		items[d.parent].append((d.item_code, round(flt(d.qty), 6), d.s_warehouse or "", d.t_warehouse or ""))

	groups = defaultdict(list)
	for name, e in by_name.items():
		if items.get(name):
			groups[(e.stock_entry_type, str(e.posting_date), tuple(sorted(items[name])))].append(name)

	findings = []
	for (entry_type, posting_date, _rows), names in groups.items():
		if len(names) < 2:
			continue
		names.sort()
		drafts = [n for n in names if by_name[n].docstatus == 0]
		labelled = ["%s (draft)" % n if n in drafts else n for n in names]
		advice = "Delete the extra draft before anyone submits it." if drafts else "One of them may have been entered twice."
		findings.append({
			"key": "DUPLICATE_STOCK_ENTRY:%s" % ":".join(names),
			"title": "%d identical %s entries on %s%s" % (
				len(names), entry_type, formatdate(posting_date), " (%d draft)" % len(drafts) if drafts else ""),
			"details": "%s have the same type, date, items, quantities and warehouses. %s" % (", ".join(labelled), advice),
			"reference_doctype": "Stock Entry", "reference_name": names[-1],
			"related_doctype": "Stock Entry", "related_name": names[0],
		})
	return findings


CHECKS = {
	"DUPLICATE_PURCHASE_INVOICE": duplicate_purchase_invoice,
	"NEGATIVE_STOCK": negative_stock,
	"UNUSUAL_JOURNAL_ENTRY": unusual_journal_entry,
	"VALUATION_JUMP": valuation_jump,
	"DUPLICATE_STOCK_ENTRY": duplicate_stock_entry,
}

# Rules about the current state: a finding that is no longer found has been fixed.
SELF_CLOSING = {"NEGATIVE_STOCK"}
