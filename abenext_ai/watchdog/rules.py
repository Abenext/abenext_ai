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
]
