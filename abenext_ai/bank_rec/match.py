# Copyright (c) 2026, Abenext. All rights reserved.
"""Rule-based matching of bank statement lines to ERPNext entries.

Pure logic with no database access, so it can be tested on its own. Each entry
can be matched to one line only. Matching runs in three passes:

1. Exact: same amount and direction, and the bank reference equals the entry's
   reference (Payment Entry reference no, Journal Entry cheque no).
2. Suggested: same amount, date within tolerance, and the party's name appears
   in the bank description. Otherwise, if exactly one entry fits, a weaker
   suggestion.
3. Grouped: two or three entries for the same party, within the date tolerance,
   that add up to the bank amount.
"""

import re
from itertools import combinations

EXACT, SUGGESTED = "Exact", "Suggested"


def _norm(text):
	return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _tokens(text):
	return set(t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if len(t) >= 3)


def same_reference(bank_ref, entry_ref):
	a, b = _norm(bank_ref), _norm(entry_ref)
	if not a or not b:
		return False
	if a == b:
		return True
	shorter, longer = sorted((a, b), key=len)
	return len(shorter) >= 6 and shorter in longer


def name_in_description(party, description):
	words = _tokens(party)
	return bool(words) and words <= _tokens(description)


def _amount(line):
	return (line["deposit"], "in") if line["deposit"] else (line["withdrawal"], "out")


def _days(a, b):
	return abs((a - b).days)


def find_matches(lines, entries, date_tolerance=3, amount_tolerance=0.0, reference_window=30):
	"""Return {line_key: {"type", "confidence", "reason", "entries": [entry, ...]}}."""
	results, used = {}, set()
	tol = max(float(amount_tolerance or 0), 0.004)

	def available(line, max_days):
		amount, direction = _amount(line)
		return [
			e for e in entries
			if e["id"] not in used and e["direction"] == direction
			and abs(e["amount"] - amount) <= tol and _days(e["date"], line["date"]) <= max_days
		]

	def record(line, kind, confidence, reason, chosen):
		results[line["key"]] = {"type": kind, "confidence": confidence, "reason": reason, "entries": chosen}
		used.update(e["id"] for e in chosen)

	# Pass 1: reference, amount and direction agree.
	for line in lines:
		if not line.get("reference"):
			continue
		options = [e for e in available(line, reference_window) if same_reference(line["reference"], e.get("reference"))]
		if options:
			best = min(options, key=lambda e: _days(e["date"], line["date"]))
			gap = _days(best["date"], line["date"])
			when = "on the same date" if gap == 0 else "%d day(s) apart" % gap
			record(line, EXACT, 100, "Amount and reference %s agree, %s." % (line["reference"], when), [best])

	# Pass 2: amount and date, preferably with the party named in the description.
	for line in lines:
		if line["key"] in results:
			continue
		options = available(line, date_tolerance)
		named = [e for e in options if name_in_description(e.get("party"), line["description"])]
		if len(named) == 1:
			e = named[0]
			record(line, SUGGESTED, 85, "Same amount within %d day(s), and %s appears in the bank description." % (date_tolerance, e["party"]), [e])
		elif len(options) == 1 and not named and not options[0].get("party"):
			# Only for entries without a party (for example a Journal Entry). Entries with a
			# party are left to the AI, which can tell that "ATM Cash Withdrawal" is not that party.
			e = options[0]
			record(line, SUGGESTED, 60, "The only entry with this amount within %d day(s). Check before accepting." % date_tolerance, [e])

	# Pass 3: several entries for one party that add up to the bank amount.
	for line in lines:
		if line["key"] in results:
			continue
		amount, direction = _amount(line)
		pool = [
			e for e in entries
			if e["id"] not in used and e["direction"] == direction and e["amount"] < amount + tol
			and _days(e["date"], line["date"]) <= date_tolerance
			and name_in_description(e.get("party"), line["description"])
		]
		by_party = {}
		for e in pool:
			by_party.setdefault(e["party"], []).append(e)
		for party, group in by_party.items():
			found = None
			for size in (2, 3):
				for combo in combinations(group[:12], size):
					if abs(sum(e["amount"] for e in combo) - amount) <= tol:
						found = list(combo)
						break
				if found:
					break
			if found:
				record(line, SUGGESTED, 80, "%d entries for %s together add up to the bank amount." % (len(found), party), found)
				break

	return results
