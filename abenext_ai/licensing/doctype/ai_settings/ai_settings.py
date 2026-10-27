# Copyright (c) 2026, Abenext. All rights reserved.

from frappe.model.document import Document


class AISettings(Document):
	def validate(self):
		if self.server_url:
			self.server_url = self.server_url.strip().rstrip("/")
