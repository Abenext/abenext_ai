# Copyright (c) 2026, Abenext. All rights reserved.
"""Read bank statement lines from text-based PDFs.

Columns are found from the header row on every page, using the keywords in
an AI Bank Format. Each word is assigned to the column whose header is
nearest to the word's centre, so empty debit or credit cells stay empty and
multi-line descriptions are joined. This module does not touch the database.
"""

import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

DEFAULT_LAYOUT = {
	"date_formats": ["%d %b %Y", "%d/%m/%Y", "%d-%m-%Y", "%d-%b-%Y", "%Y-%m-%d"],
	"columns": {
		"date": ["booking date", "transaction date", "txn date", "value date", "date"],
		"description": ["description", "narration", "particulars", "details"],
		"debit": ["debit", "withdrawal", "withdrawals", "dr"],
		"credit": ["credit", "deposit", "deposits", "cr"],
		"balance": ["available balance", "running balance", "balance"],
	},
	"opening_balance_label": "opening balance",
	"closing_balance_label": "closing balance",
	"footer_margin": 40,
	"ignore_line_patterns": [],
}

AMOUNT_TOKEN = re.compile(r"^[+-]?\(?(?:[A-Z]{3})?\s*-?[\d,]+(?:\.\d+)?\)?(?:\s*(?:CR|DR))?$", re.I)


class StatementError(Exception):
	pass


def money(raw):
	"""Convert '+ PKR15,000.00', 'PKR904,576.07', '(1,200.50)' or '35 DR' to Decimal."""
	text = str(raw or "").strip().upper().replace(" ", "")
	if text in ("", "-", "--"):
		return None
	negative = text.startswith("-") or (text.startswith("(") and text.endswith(")")) or text.endswith("DR")
	text = re.sub(r"(CR|DR)$", "", text)
	text = re.sub(r"[^\d.]", "", text)
	if not text:
		return None
	try:
		value = Decimal(text).quantize(Decimal("0.01"))
	except InvalidOperation:
		raise StatementError("Invalid amount: %r" % raw)
	return -value if negative else value


def load_layout(column_map=None, date_format=None):
	layout = json.loads(json.dumps(DEFAULT_LAYOUT))
	if column_map:
		custom = json.loads(column_map) if isinstance(column_map, str) else column_map
		for key, value in custom.items():
			if key == "columns":
				layout["columns"].update(value)
			else:
				layout[key] = value
	if date_format:
		layout["date_formats"] = [date_format] + [f for f in layout["date_formats"] if f != date_format]
	return layout


def parse_date(text, formats):
	text = (text or "").strip()
	for fmt in formats:
		try:
			return datetime.strptime(text, fmt).date()
		except ValueError:
			continue
	return None


def _lines(words, tolerance=3):
	"""Group words into visual lines by their top position."""
	lines = []
	for word in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
		if lines and abs(lines[-1]["top"] - word["top"]) <= tolerance:
			lines[-1]["words"].append(word)
		else:
			lines.append({"top": word["top"], "words": [word]})
	for line in lines:
		line["words"].sort(key=lambda w: w["x0"])
		line["text"] = " ".join(w["text"] for w in line["words"])
	return lines


def _find_header(line, layout):
	"""Return {column: centre_x} if this line is the table header, else None."""
	text = line["text"].lower()
	found = {}
	for column, keywords in layout["columns"].items():
		for keyword in sorted(keywords, key=len, reverse=True):
			parts = keyword.split()
			for i, word in enumerate(line["words"]):
				chunk = [w["text"].lower() for w in line["words"][i:i + len(parts)]]
				if chunk == parts:
					first, last = line["words"][i], line["words"][i + len(parts) - 1]
					found[column] = (first["x0"] + last["x1"]) / 2
					break
			if column in found:
				break
	required = {"date", "description", "balance"}
	if required <= set(found) and ("debit" in found or "credit" in found) and len(text) < 200:
		return found
	return None


def _column_of(word, centres):
	middle = (word["x0"] + word["x1"]) / 2
	return min(centres, key=lambda c: abs(centres[c] - middle))


def _label_value(lines, label):
	"""Find a value printed under a label such as 'Opening Balance'."""
	parts = label.lower().split()
	for index, line in enumerate(lines):
		words = line["words"]
		for i in range(len(words) - len(parts) + 1):
			if [w["text"].lower() for w in words[i:i + len(parts)]] == parts:
				x0 = words[i]["x0"]
				for below in lines[index + 1:index + 3]:
					for w in below["words"]:
						if abs(w["x0"] - x0) < 15 and AMOUNT_TOKEN.match(w["text"]):
							return money(w["text"])
	return None


def extract_text_pages(pdf_path):
	import pdfplumber

	pages = []
	with pdfplumber.open(pdf_path) as pdf:
		for page in pdf.pages:
			pages.append({"height": page.height, "words": page.extract_words(keep_blank_chars=False)})
	if not any(p["words"] for p in pages):
		raise StatementError("No readable text in this PDF. It may be a scanned copy.")
	return pages


def page_text(pages, first=1):
	return " ".join(w["text"] for p in pages[:first] for w in p["words"])


def parse_statement(pages, layout):
	"""Turn PDF words into statement lines and run the running-balance check."""
	ignore = [re.compile(p) for p in layout.get("ignore_line_patterns") or []]
	all_first_page_lines = _lines(pages[0]["words"]) if pages else []
	opening = _label_value(all_first_page_lines, layout["opening_balance_label"])
	closing = _label_value(all_first_page_lines, layout["closing_balance_label"])

	rows, rejected, centres = [], [], None
	for page_no, page in enumerate(pages, 1):
		bottom = page["height"] - (layout.get("footer_margin") or 0)
		in_table = False
		for line in _lines(page["words"]):
			if line["top"] > bottom or any(p.search(line["text"]) for p in ignore):
				continue
			header = _find_header(line, layout)
			if header:
				centres, in_table = header, True
				continue
			if not in_table or not centres:
				continue

			cells = {c: [] for c in centres}
			for word in line["words"]:
				cells[_column_of(word, centres)].append(word["text"])
			cells = {c: " ".join(v).strip() for c, v in cells.items()}

			row_date, spill = _leading_date(cells.get("date", ""), layout["date_formats"])
			if row_date:
				rows.append({
					"date": row_date, "description": (spill + " " + cells.get("description", "")).strip(),
					"debit_raw": cells.get("debit", ""), "credit_raw": cells.get("credit", ""),
					"balance_raw": cells.get("balance", ""), "page": page_no,
				})
			elif rows:
				last = rows[-1]
				extra = " ".join(v for c, v in cells.items() if c in ("date", "description") and v)
				if extra:
					joiner = "" if last["description"].endswith("-") else " "
					last["description"] = (last["description"] + joiner + extra).strip()
				for column in ("debit", "credit", "balance"):
					if cells.get(column) and not last[column + "_raw"]:
						last[column + "_raw"] = cells[column]

	if centres is None:
		raise StatementError("Could not find the table header (Date, Description, Balance) in this PDF.")

	result, previous = [], opening
	for number, row in enumerate(rows, 1):
		try:
			debit = money(row["debit_raw"]) or Decimal("0.00")
			credit = money(row["credit_raw"]) or Decimal("0.00")
			balance = money(row["balance_raw"])
		except StatementError as exc:
			rejected.append({"line": number, "page": row["page"], "reason": str(exc)})
			continue
		debit, credit = abs(debit), abs(credit)
		if balance is None or (debit and credit) or not (debit or credit):
			rejected.append({"line": number, "page": row["page"],
				"reason": "Line needs exactly one of debit or credit, and a balance"})
			continue
		ok = previous is None or (previous + credit - debit) == balance
		result.append({
			"date": row["date"].isoformat(), "description": row["description"],
			"reference_no": _reference(row["description"]),
			"debit": str(debit), "credit": str(credit), "balance": str(balance),
			"balance_ok": ok, "page": row["page"],
		})
		previous = balance

	closing_ok = closing is None or (result and Decimal(result[-1]["balance"]) == closing)
	return {
		"opening_balance": str(opening) if opening is not None else None,
		"closing_balance": str(closing) if closing is not None else None,
		"from_date": result[0]["date"] if result else None,
		"to_date": result[-1]["date"] if result else None,
		"lines": result,
		"rejected": rejected,
		"mismatches": sum(1 for r in result if not r["balance_ok"]),
		"closing_ok": bool(closing_ok),
	}


def _leading_date(text, formats):
	"""Read a date from the start of the date cell; return (date, leftover words)."""
	tokens = (text or "").split()
	for size in range(min(4, len(tokens)), 0, -1):
		found = parse_date(" ".join(tokens[:size]), formats)
		if found:
			return found, " ".join(tokens[size:])
	return None, ""


def _reference(description):
	"""STAN number if present, otherwise the longest bank reference code in the text."""
	text = description or ""
	match = re.search(r"STAN\s*\(?\s*(\d{4,})\s*\)?", text, re.I)
	if match:
		return match.group(1)
	codes = [t for t in re.findall(r"[A-Z0-9]{16,}", text) if re.search(r"\d", t)]
	return max(codes, key=len) if codes else ""


def read_pdf(pdf_path, column_map=None, date_format=None):
	return parse_statement(extract_text_pages(pdf_path), load_layout(column_map, date_format))
