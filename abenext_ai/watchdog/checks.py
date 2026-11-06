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


def duplicate_payment(company, rule):
	days = int(rule.threshold or 3)
	rows = frappe.db.sql(
		"""
		select a.name as first, b.name as second, a.party_type, a.party, a.paid_amount, a.payment_type,
			a.reference_no, b.reference_no as second_ref
		from `tabPayment Entry` a
		join `tabPayment Entry` b
			on b.company = a.company and b.party_type = a.party_type and b.party = a.party
			and b.payment_type = a.payment_type and b.paid_amount = a.paid_amount
			and b.name > a.name and b.docstatus = 1
		where a.docstatus = 1 and a.company = %(company)s and ifnull(a.party, '') != ''
			and a.payment_type in ('Pay', 'Receive') and a.posting_date >= %(since)s
			and (
				(ifnull(a.reference_no, '') != '' and a.reference_no = b.reference_no)
				or abs(datediff(a.posting_date, b.posting_date)) <= %(days)s
			)
		limit 200
		""",
		{"company": company, "since": _since(rule), "days": days},
		as_dict=True,
	)
	findings = []
	for r in rows:
		same_ref = r.reference_no and r.reference_no == r.second_ref
		why = "the same reference %s" % r.reference_no if same_ref else "within %d days" % days
		verb = "paid to" if r.payment_type == "Pay" else "received from"
		findings.append({
			"key": "DUPLICATE_PAYMENT:%s:%s" % (r.first, r.second),
			"title": "Possible duplicate payment %s %s" % (verb, r.party),
			"details": "%s and %s both show %s %s %s, with %s." % (
				r.first, r.second, fmt_money(r.paid_amount), verb, r.party, why),
			"reference_doctype": "Payment Entry", "reference_name": r.second,
			"related_doctype": "Payment Entry", "related_name": r.first,
			"amount": r.paid_amount,
		})
	return findings


def _norm_account(number):
	return "".join(ch for ch in str(number or "").upper() if ch.isalnum())


def shared_bank_account(company, rule):
	owners = defaultdict(set)
	for row in frappe.get_all(
		"Bank Account",
		filters={"is_company_account": 0, "party": ["is", "set"]},
		fields=["name", "party_type", "party", "bank_account_no", "iban"],
		limit=20000,
	):
		for number in (row.bank_account_no, row.iban):
			key = _norm_account(number)
			if len(key) >= 6:
				owners[key].add((row.party_type, row.party, "Bank Account", row.name))
	meta = frappe.get_meta("Employee") if frappe.db.exists("DocType", "Employee") else None
	if meta and meta.has_field("bank_ac_no"):
		for row in frappe.get_all("Employee", filters={"bank_ac_no": ["is", "set"], "company": company},
				fields=["name", "employee_name", "bank_ac_no"], limit=20000):
			key = _norm_account(row.bank_ac_no)
			if len(key) >= 6:
				owners[key].add(("Employee", row.employee_name or row.name, "Employee", row.name))
	findings = []
	for number, people in owners.items():
		parties = {(p[0], p[1]) for p in people}
		if len(parties) < 2:
			continue
		people = sorted(people)
		names = ", ".join("%s %s" % (p[0], p[1]) for p in people)
		findings.append({
			"key": "SHARED_BANK_ACCOUNT:%s" % number,
			"title": "Same bank account used by %d parties" % len(parties),
			"details": "Bank account ending %s is recorded for %s. Check that each payee is genuine." % (number[-4:], names),
			"reference_doctype": people[0][2], "reference_name": people[0][3],
			"related_doctype": people[1][2], "related_name": people[1][3],
		})
	return findings


def duplicate_sales_invoice(company, rule):
	days = int(rule.threshold or 3)
	rows = frappe.db.sql(
		"""
		select a.name as first, b.name as second, a.customer, a.grand_total
		from `tabSales Invoice` a
		join `tabSales Invoice` b
			on b.customer = a.customer and b.company = a.company and b.grand_total = a.grand_total
			and b.name > a.name and b.docstatus = 1 and b.is_return = 0
		where a.docstatus = 1 and a.is_return = 0 and a.company = %(company)s and a.posting_date >= %(since)s
			and abs(datediff(a.posting_date, b.posting_date)) <= %(days)s
		limit 200
		""",
		{"company": company, "since": _since(rule), "days": days},
		as_dict=True,
	)
	return [{
		"key": "DUPLICATE_SALES_INVOICE:%s:%s" % (r.first, r.second),
		"title": "Possible duplicate invoice to %s" % r.customer,
		"details": "%s and %s are both for %s with the same amount (%s) within %d days." % (
			r.first, r.second, r.customer, fmt_money(r.grand_total), days),
		"reference_doctype": "Sales Invoice", "reference_name": r.second,
		"related_doctype": "Sales Invoice", "related_name": r.first,
		"amount": r.grand_total,
	} for r in rows]


def negative_cash(company, rule):
	rows = frappe.db.sql(
		"""
		select gle.account, sum(gle.debit - gle.credit) as balance
		from `tabGL Entry` gle
		join `tabAccount` acc on acc.name = gle.account
		where gle.company = %(company)s and gle.is_cancelled = 0 and acc.account_type = 'Cash' and acc.is_group = 0
		group by gle.account
		having balance < -0.005
		""",
		{"company": company},
		as_dict=True,
	)
	return [{
		"key": "NEGATIVE_CASH:%s" % r.account,
		"title": "Negative cash balance in %s" % r.account,
		"details": "%s shows %s. Cash cannot be below zero; a receipt is probably missing or a payment was entered twice." % (
			r.account, fmt_money(r.balance)),
		"reference_doctype": "Account", "reference_name": r.account,
		"amount": r.balance,
	} for r in rows]


def selling_below_cost(company, rule):
	allowed = flt(rule.threshold) / 100
	rows = frappe.db.sql(
		"""
		select si.name, si.customer, si.posting_date, sii.item_code, sii.qty, sii.base_net_rate,
			coalesce(nullif(sii.incoming_rate, 0), bin.valuation_rate, 0) as cost
		from `tabSales Invoice Item` sii
		join `tabSales Invoice` si on si.name = sii.parent
		join `tabItem` item on item.name = sii.item_code and item.is_stock_item = 1
		left join `tabBin` bin on bin.item_code = sii.item_code and bin.warehouse = sii.warehouse
		where si.docstatus = 1 and si.is_return = 0 and si.company = %(company)s and si.posting_date >= %(since)s
			and sii.qty > 0
		limit 5000
		""",
		{"company": company, "since": _since(rule)},
		as_dict=True,
	)
	findings = []
	for r in rows:
		cost = flt(r.cost)
		if cost <= 0 or flt(r.base_net_rate) >= cost * (1 - allowed):
			continue
		loss = (cost - flt(r.base_net_rate)) * flt(r.qty)
		findings.append({
			"key": "SELLING_BELOW_COST:%s:%s" % (r.name, r.item_code),
			"title": "%s sold below cost on %s" % (r.item_code, r.name),
			"details": "%s to %s on %s: %s sold at %s each against a cost of %s (loss about %s)." % (
				r.name, r.customer, formatdate(r.posting_date), r.item_code,
				fmt_money(r.base_net_rate), fmt_money(cost), fmt_money(loss)),
			"reference_doctype": "Sales Invoice", "reference_name": r.name, "amount": loss,
		})
	return findings


BACKDATE_DOCTYPES = {
	"Sales Invoice": "grand_total",
	"Purchase Invoice": "grand_total",
	"Payment Entry": "paid_amount",
	"Journal Entry": "total_debit",
	"Stock Entry": "total_outgoing_value",
}


def backdated_entry(company, rule):
	days = int(rule.threshold or 30)
	findings = []
	for doctype, amount_field in BACKDATE_DOCTYPES.items():
		opening = "and ifnull(is_opening, 'No') != 'Yes'" if frappe.get_meta(doctype).has_field("is_opening") else ""
		rows = frappe.db.sql(
			"""
			select name, posting_date, date(creation) as entered, `{amount}` as amount
			from `tab{doctype}`
			where docstatus = 1 and company = %(company)s and creation >= %(since)s
				and datediff(date(creation), posting_date) > %(days)s {opening}
			limit 300
			""".format(doctype=doctype, amount=amount_field, opening=opening),
			{"company": company, "since": _since(rule), "days": days},
			as_dict=True,
		)
		for r in rows:
			late = (getdate(r.entered) - getdate(r.posting_date)).days
			findings.append({
				"key": "BACKDATED_ENTRY:%s:%s" % (doctype, r.name),
				"title": "%s %s back-dated by %d days" % (doctype, r.name, late),
				"details": "%s was entered on %s with a posting date of %s. Check why it was dated %d days earlier." % (
					r.name, formatdate(r.entered), formatdate(r.posting_date), late),
				"reference_doctype": doctype, "reference_name": r.name, "amount": r.amount,
			})
	return findings


def old_uncleared_bank(company, rule):
	days = int(rule.threshold or 30)
	before = add_days(nowdate(), -days)
	rows = frappe.db.sql(
		"""
		select account, count(*) as entries, sum(amount) as total, min(posting_date) as oldest
		from (
			select pe.paid_from as account, pe.paid_amount as amount, pe.posting_date
			from `tabPayment Entry` pe join `tabAccount` acc on acc.name = pe.paid_from
			where pe.docstatus = 1 and pe.company = %(company)s and acc.account_type = 'Bank'
				and pe.clearance_date is null and pe.posting_date between %(since)s and %(before)s
			union all
			select pe.paid_to, pe.received_amount, pe.posting_date
			from `tabPayment Entry` pe join `tabAccount` acc on acc.name = pe.paid_to
			where pe.docstatus = 1 and pe.company = %(company)s and acc.account_type = 'Bank'
				and pe.clearance_date is null and pe.posting_date between %(since)s and %(before)s
			union all
			select jea.account, abs(jea.debit - jea.credit), je.posting_date
			from `tabJournal Entry Account` jea join `tabJournal Entry` je on je.name = jea.parent
			join `tabAccount` acc on acc.name = jea.account
			where je.docstatus = 1 and je.company = %(company)s and acc.account_type = 'Bank'
				and je.clearance_date is null and je.posting_date between %(since)s and %(before)s
		) uncleared
		group by account
		""",
		{"company": company, "since": _since(rule), "before": before},
		as_dict=True,
	)
	return [{
		"key": "OLD_UNCLEARED_BANK:%s" % r.account,
		"title": "%d entries on %s not seen on the bank statement" % (r.entries, r.account),
		"details": "%d payment(s) and journal entries totalling %s on %s are older than %d days and still have no "
		"clearance date; the oldest is from %s. Reconcile the bank account, or check whether these really happened." % (
			r.entries, fmt_money(r.total), r.account, days, formatdate(r.oldest)),
		"reference_doctype": "Account", "reference_name": r.account, "amount": r.total,
	} for r in rows]


def credit_limit_exceeded(company, rule):
	rows = frappe.db.sql(
		"""
		select ccl.parent as customer, ccl.credit_limit,
			(select coalesce(sum(si.outstanding_amount), 0) from `tabSales Invoice` si
				where si.customer = ccl.parent and si.company = ccl.company and si.docstatus = 1) as outstanding
		from `tabCustomer Credit Limit` ccl
		where ccl.parenttype = 'Customer' and ccl.company = %(company)s and ccl.credit_limit > 0
		""",
		{"company": company},
		as_dict=True,
	)
	return [{
		"key": "CREDIT_LIMIT_EXCEEDED:%s:%s" % (company, r.customer),
		"title": "%s is over the credit limit" % r.customer,
		"details": "%s owes %s against a credit limit of %s (over by %s)." % (
			r.customer, fmt_money(r.outstanding), fmt_money(r.credit_limit), fmt_money(flt(r.outstanding) - flt(r.credit_limit))),
		"reference_doctype": "Customer", "reference_name": r.customer,
		"amount": flt(r.outstanding) - flt(r.credit_limit),
	} for r in rows if flt(r.outstanding) > flt(r.credit_limit)]


CHECKS = {
	"DUPLICATE_PURCHASE_INVOICE": duplicate_purchase_invoice,
	"NEGATIVE_STOCK": negative_stock,
	"UNUSUAL_JOURNAL_ENTRY": unusual_journal_entry,
	"VALUATION_JUMP": valuation_jump,
	"DUPLICATE_STOCK_ENTRY": duplicate_stock_entry,
	"DUPLICATE_PAYMENT": duplicate_payment,
	"SHARED_BANK_ACCOUNT": shared_bank_account,
	"DUPLICATE_SALES_INVOICE": duplicate_sales_invoice,
	"NEGATIVE_CASH": negative_cash,
	"SELLING_BELOW_COST": selling_below_cost,
	"BACKDATED_ENTRY": backdated_entry,
	"OLD_UNCLEARED_BANK": old_uncleared_bank,
	"CREDIT_LIMIT_EXCEEDED": credit_limit_exceeded,
}

# Rules about the current state: a finding that is no longer found has been fixed.
SELF_CLOSING = {"NEGATIVE_STOCK", "NEGATIVE_CASH", "OLD_UNCLEARED_BANK", "CREDIT_LIMIT_EXCEEDED"}

# Rules whose finding describes a changing state: its text and amount are refreshed every night.
REFRESHED = {"NEGATIVE_STOCK", "NEGATIVE_CASH", "OLD_UNCLEARED_BANK", "CREDIT_LIMIT_EXCEEDED"}
