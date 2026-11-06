# Copyright (c) 2026, Abenext. All rights reserved.

import frappe
from frappe import _
from frappe.model.document import Document


class AICollectionsSettings(Document):
	def validate(self):
		if self.send_reminders and self.test_mode and not self.test_recipient:
			frappe.throw(_("Set a Test Recipient, or turn Test Mode off."))
		days = [row.days_overdue for row in self.stages]
		if len(days) != len(set(days)):
			frappe.throw(_("Two stages have the same Days Overdue."))
		self.stages.sort(key=lambda row: row.days_overdue)
		for i, row in enumerate(self.stages, 1):
			row.idx = i
