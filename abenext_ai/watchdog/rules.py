# Copyright (c) 2026, Abenext. All rights reserved.
"""The rules shipped with Abenext AI Watchdog.

A new version of the app can add rules here. On migrate, missing rules are
created; rules a client already has are never overwritten, so their thresholds
and on/off choices are kept.
"""

RULES = [
	{
		"rule_code": "DUPLICATE_PURCHASE_INVOICE",
		"rule_name": "Duplicate supplier invoice",
		"severity": "High",
		"threshold": 3,
		"threshold_label": "Days apart for invoices with the same supplier and amount",
		"lookback_days": 90,
		"description": "Two submitted Purchase Invoices from the same supplier with the same bill number, "
		"or with the same amount within the threshold days.",
	},
	{
		"rule_code": "NEGATIVE_STOCK",
		"rule_name": "Negative stock",
		"severity": "High",
		"threshold": 0,
		"threshold_label": "Not used",
		"lookback_days": 0,
		"description": "Any item whose quantity in a warehouse is below zero. Closes itself when the stock is corrected.",
	},
	{
		"rule_code": "UNUSUAL_JOURNAL_ENTRY",
		"rule_name": "Unusual Journal Entry",
		"severity": "Medium",
		"threshold": 500000,
		"threshold_label": "Smallest round amount to report",
		"lookback_days": 30,
		"description": "Journal Entries of a large round amount posted to cash or bank without a reference, "
		"and manual Journal or Cash Entries posted on a Sunday or a holiday.",
	},
	{
		"rule_code": "VALUATION_JUMP",
		"rule_name": "Valuation jump",
		"severity": "Medium",
		"threshold": 50,
		"threshold_label": "Percent difference from the item's average incoming rate of the previous 90 days",
		"lookback_days": 30,
		"description": "Stock received at a rate far above or below what the item usually costs in that warehouse.",
	},
	{
		"rule_code": "DUPLICATE_STOCK_ENTRY",
		"rule_name": "Duplicate Stock Entry",
		"severity": "Medium",
		"threshold": 0,
		"threshold_label": "Not used",
		"lookback_days": 30,
		"description": "Submitted Stock Entries with the same type, date, items, quantities and warehouses.",
	},
	{
		"rule_code": "DUPLICATE_PAYMENT",
		"rule_name": "Duplicate payment",
		"severity": "High",
		"threshold": 3,
		"threshold_label": "Days apart for payments with the same party and amount",
		"lookback_days": 90,
		"description": "Two submitted Payment Entries to or from the same party for the same amount, "
		"with the same reference number or within the threshold days.",
	},
	{
		"rule_code": "SHARED_BANK_ACCOUNT",
		"rule_name": "Same bank account on two parties",
		"severity": "High",
		"threshold": 0,
		"threshold_label": "Not used",
		"lookback_days": 0,
		"description": "One bank account number or IBAN recorded for two different suppliers, customers or employees.",
	},
	{
		"rule_code": "DUPLICATE_SALES_INVOICE",
		"rule_name": "Duplicate sales invoice",
		"severity": "High",
		"threshold": 3,
		"threshold_label": "Days apart for invoices with the same customer and amount",
		"lookback_days": 90,
		"description": "Two submitted Sales Invoices for the same customer and amount within the threshold days.",
	},
	{
		"rule_code": "NEGATIVE_CASH",
		"rule_name": "Negative cash balance",
		"severity": "High",
		"threshold": 0,
		"threshold_label": "Not used",
		"lookback_days": 0,
		"description": "A cash account whose balance is below zero. Closes itself when corrected.",
	},
	{
		"rule_code": "SELLING_BELOW_COST",
		"rule_name": "Selling below cost",
		"severity": "Medium",
		"threshold": 0,
		"threshold_label": "Percent below cost allowed before reporting",
		"lookback_days": 30,
		"description": "Sales Invoice lines sold below the item's cost (its incoming rate, or the warehouse valuation rate).",
	},
	{
		"rule_code": "BACKDATED_ENTRY",
		"rule_name": "Back-dated entry",
		"severity": "Medium",
		"threshold": 30,
		"threshold_label": "Days between the posting date and the day it was entered",
		"lookback_days": 30,
		"description": "Invoices, payments, Journal Entries and Stock Entries submitted with a posting date far before "
		"the day they were entered. Opening entries are skipped.",
	},
	{
		"rule_code": "OLD_UNCLEARED_BANK",
		"rule_name": "Old uncleared bank entries",
		"severity": "Medium",
		"threshold": 30,
		"threshold_label": "Days after which an entry should have appeared on the bank statement",
		"lookback_days": 365,
		"description": "Payments and Journal Entries on a bank account with no clearance date after the threshold days. "
		"One finding per bank account, updated every night; closes itself when everything is cleared.",
	},
	{
		"rule_code": "CREDIT_LIMIT_EXCEEDED",
		"rule_name": "Credit limit exceeded",
		"severity": "Medium",
		"threshold": 0,
		"threshold_label": "Not used",
		"lookback_days": 0,
		"description": "Customers whose unpaid invoices are above their credit limit for the company. Closes itself when back under.",
	},
]
