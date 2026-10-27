# Copyright (c) 2026, Abenext. All rights reserved.

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class AIWatchdogFinding(Document):
	def validate(self):
		if self.has_value_changed("status"):
			if self.status in ("Fixed", "Ignored"):
				self.resolved_by = frappe.session.user
				self.resolved_on = now_datetime()
			else:
				self.resolved_by = None
				self.resolved_on = None
