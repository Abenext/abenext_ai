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
	# Rows inside the table that carry the opening or closing balance instead of a transaction.
	"opening_row_labels": ["opening balance", "balance b/f", "balance brought forward", "balance forward"],
	"closing_row_labels": ["closing balance", "balance c/f", "balance carried forward"],
	"footer_margin": 40,
	"ignore_line_patterns": [],
	# Lines under a transaction that only carry its reference, for example "54546884055 45,000.00 0.00".
	"reference_line_patterns": [],
	# Points below a header line that still belong to the same header (headers printed over 2-3 lines).
	"header_depth": 14,
}

# Optional columns a format may name besides the usual ones:
#   "amount"    one signed column instead of debit and credit (negative, bracketed or DR = money out)
#   "fee"       a separate fee column, added to the money going out
#   "reference" a column holding the bank's reference number
#   any other name (for example "opening" or "channel") is read and ignored, so its words do not
#   spill into the description.

TIME_ONLY = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?\s*([AP]M)?$", re.I)

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
	found, starts = {}, {}
	for column, keywords in layout["columns"].items():
		for keyword in sorted(keywords, key=len, reverse=True):
			parts = keyword.split()
			for i, word in enumerate(line["words"]):
				chunk = [w["text"].lower() for w in line["words"][i:i + len(parts)]]
				if chunk == parts:
					first, last = line["words"][i], line["words"][i + len(parts) - 1]
					found[column] = (first["x0"] + last["x1"]) / 2
					starts[column] = first["x0"]
					break
			if column in found:
				break
	required = {"date", "description", "balance"}
	if required <= set(found) and ({"debit", "credit", "amount"} & set(found)) and len(text) < 250:
		found["_starts"] = starts
		return found
	return None


def _header_at(lines, index, layout):
	"""Header found on this line, alone or merged with the lines printed just below it.

	Returns (centres, number_of_lines_used) or (None, 0).
	"""
	top = lines[index]["top"]
	group = []
	for line in lines[index:index + 3]:
		if line["top"] - top > (layout.get("header_depth") or 0) and group:
			break
		group.append(line)
		words = sorted((w for l in group for w in l["words"]), key=lambda w: (round(w["x0"]), w["top"]))
		merged = {"top": top, "words": words, "text": " ".join(w["text"] for w in words)}
		found = _find_header(merged, layout)
		if found:
			return found, len(group)
	return None, 0


def _column_of(word, centres, starts=None, wide_description=False):
	middle = (word["x0"] + word["x1"]) / 2
	if wide_description and starts and "description" in starts:
		begin = starts["description"]
		later = [x for x in starts.values() if x > begin + 1]
		if begin - 5 <= middle < (min(later) - 5 if later else float("inf")):
			return "description"
	return min(centres, key=lambda c: abs(centres[c] - middle))


def _label_value(lines, label):
	"""Find a value printed under a label such as 'Opening Balance'."""
	parts = label.lower().split()
	for index, line in enumerate(lines):
		words = line["words"]
		for i in range(len(words) - len(parts) + 1):
			if [w["text"].lower().rstrip(":") for w in words[i:i + len(parts)]] == parts:
				x0, x1 = words[i]["x0"], words[i + len(parts) - 1]["x1"]
				for below in lines[index + 1:index + 3]:
					for w in below["words"]:
						lined_up = abs(w["x0"] - x0) < 15 or (w["x0"] < x1 and w["x1"] > x0)
						if lined_up and AMOUNT_TOKEN.match(w["text"]):
							return money(w["text"])
	return None


def _balance_label(text, layout):
	"""'opening' or 'closing' if this row only carries a balance, else None."""
	text = " ".join((text or "").lower().split())
	for label in sorted(layout.get("closing_row_labels") or [], key=len, reverse=True):
		if text.startswith(label):
			return "closing"
	for label in sorted(layout.get("opening_row_labels") or [], key=len, reverse=True):
		if text.startswith(label):
			return "opening"
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
	ignore = [re.compile(p, re.I) for p in layout.get("ignore_line_patterns") or []]
	ref_lines = [re.compile(p) for p in layout.get("reference_line_patterns") or []]
	all_first_page_lines = _lines(pages[0]["words"]) if pages else []
	opening = _label_value(all_first_page_lines, layout["opening_balance_label"])
	closing = _label_value(all_first_page_lines, layout["closing_balance_label"])
	row_opening = row_closing = None
	money_columns = ("debit", "credit", "amount", "fee", "balance")

	rows, rejected, centres, starts = [], [], None, {}
	for page_no, page in enumerate(pages, 1):
		bottom = page["height"] - (layout.get("footer_margin") or 0)
		in_table = False
		page_lines = _lines(page["words"])
		skip = 0
		for index, line in enumerate(page_lines):
			if skip:
				skip -= 1
				continue
			if line["top"] > bottom or any(p.search(line["text"]) for p in ignore):
				continue
			header, used = _header_at(page_lines, index, layout)
			if header:
				starts = header.pop("_starts", {})
				centres, in_table, skip = header, True, used - 1
				continue
			if not in_table or not centres:
				continue

			if rows and any(p.search(line["text"]) for p in ref_lines):
				match = next(p.search(line["text"]) for p in ref_lines if p.search(line["text"]))
				rows[-1]["reference"] = rows[-1].get("reference") or (match.group(1) if match.groups() else match.group(0))
				continue

			cells = {c: [] for c in centres}
			for word in line["words"]:
				cells[_column_of(word, centres, starts, layout.get("wide_description"))].append(word["text"])
			cells = {c: " ".join(v).strip() for c, v in cells.items()}

			row_date, spill = _leading_date(cells.get("date", ""), layout["date_formats"])
			label_text = (spill if row_date else cells.get("date", "")) + " " + cells.get("description", "")
			label = _balance_label(label_text, layout)
			if label:
				value = money(cells.get("balance")) if cells.get("balance") else None
				if value is None and label == "opening":
					value = money(cells.get("opening")) if cells.get("opening") else None
				if label == "opening":
					row_opening = value
				else:
					row_closing = value
				continue

			if row_date:
				rows.append(dict({column + "_raw": cells.get(column, "") for column in money_columns},
					date=row_date, description=(spill + " " + cells.get("description", "")).strip(),
					reference=cells.get("reference", ""), page=page_no))
			elif rows:
				last = rows[-1]
				date_part = "" if TIME_ONLY.match(cells.get("date", "")) else cells.get("date", "")
				extra = " ".join(v for v in (date_part, cells.get("description", "")) if v)
				if extra:
					joiner = "" if (last["description"].endswith("-") and not last["description"].endswith(" -")) else " "
					last["description"] = (last["description"] + joiner + extra).strip()
				if cells.get("reference") and not last.get("reference"):
					last["reference"] = cells["reference"]
				for column in money_columns:
					if cells.get(column) and not last[column + "_raw"]:
						last[column + "_raw"] = cells[column]

	if centres is None:
		raise StatementError("Could not find the table header (Date, Description, Balance) in this PDF.")

	# Rows printed inside the table win over values found near labels at the top of the page.
	opening = row_opening if row_opening is not None else opening
	closing = row_closing if row_closing is not None else closing
	# Some banks list the newest transaction first.
	if len(rows) > 1 and rows[0]["date"] > rows[-1]["date"]:
		rows.reverse()

	result, previous = [], opening
	for number, row in enumerate(rows, 1):
		try:
			debit = money(row["debit_raw"]) or Decimal("0.00")
			credit = money(row["credit_raw"]) or Decimal("0.00")
			amount = money(row["amount_raw"])
			fee = abs(money(row["fee_raw"]) or Decimal("0.00"))
			balance = money(row["balance_raw"])
		except StatementError as exc:
			rejected.append({"line": number, "page": row["page"], "reason": str(exc)})
			continue
		debit, credit = abs(debit), abs(credit)
		if amount is not None and not (debit or credit):
			debit, credit = (abs(amount), Decimal("0.00")) if amount < 0 else (Decimal("0.00"), amount)
		debit += fee
		if balance is None or (debit and credit) or not (debit or credit):
			rejected.append({"line": number, "page": row["page"],
				"reason": "Line needs exactly one of debit or credit, and a balance"})
			continue
		ok = previous is None or (previous + credit - debit) == balance
		result.append({
			"date": row["date"].isoformat(), "description": row["description"],
			"reference_no": (row.get("reference") or "").strip() or _reference(row["description"]),
			"debit": str(debit), "credit": str(credit), "balance": str(balance),
			"balance_ok": ok, "page": row["page"],
		})
		previous = balance

	if result:
		closing_ok = closing is None or Decimal(result[-1]["balance"]) == closing
	else:
		closing_ok = closing is None or opening is None or opening == closing
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
