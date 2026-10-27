# Copyright (c) 2026, Abenext. All rights reserved.
"""The only file that talks to the Abenext server.

Every request is signed with HMAC-SHA256 using this site's signing secret. The
secret is never sent. No AI provider key is stored on client sites.
"""

import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import urlparse

import frappe
import requests
from frappe import _
from frappe.utils import now_datetime

ENDPOINT = "/api/method/abenext_server.api.process"
TIMEOUT = (10, 120)


class AIServerError(Exception):
	pass


def site_url():
	"""This site's public address. Set host_name in site config so background jobs report it correctly."""
	return (frappe.conf.get("host_name") or frappe.utils.get_url()).strip().rstrip("/")


def _settings():
	settings = frappe.get_single("AI Settings")
	url = (settings.server_url or "").strip().rstrip("/")
	parsed = urlparse(url)
	if parsed.scheme != "https" or not parsed.netloc:
		raise AIServerError(_("Set a valid https Server URL in AI Settings."))
	secret = settings.get_password("signing_secret", raise_exception=False)
	if not settings.license_id or not secret:
		raise AIServerError(_("Set the License ID and Signing Secret in AI Settings."))
	return url, settings.license_id.strip(), secret


def process(task, payload=None):
	"""Send one task to the Abenext server and return its result (a dict)."""
	url, license_id, secret = _settings()
	body = json.dumps({
		"site_url": site_url(),
		"task": task,
		"payload": payload or {},
		"timestamp": int(time.time()),
		"nonce": secrets.token_hex(16),
	}, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode("utf-8")
	signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

	try:
		response = requests.post(url + ENDPOINT, data=body, timeout=TIMEOUT, headers={
			"Content-Type": "application/json",
			"X-Abenext-License": license_id,
			"X-Abenext-Signature": signature,
		})
	except requests.Timeout:
		raise AIServerError(_("The Abenext server did not answer in time."))
	except requests.RequestException:
		raise AIServerError(_("The Abenext server could not be reached. Check the Server URL and this server's internet access."))

	try:
		data = response.json().get("message") or {}
	except ValueError:
		data = {}
	if response.status_code != 200 or not data.get("ok"):
		_remember_license(data.get("license") or {})
		reason = data.get("error") or _("The Abenext server returned an error (HTTP {0}).").format(response.status_code)
		raise AIServerError(reason)
	_remember_license(data.get("license") or {})
	return data.get("result") or {}


def _remember_license(info):
	if not info:
		return
	old_status = frappe.db.get_single_value("AI Settings", "license_status")
	values = {"last_sync": now_datetime()}
	for field in ("status", "valid_till", "modules"):
		if field in info:
			target = {"status": "license_status", "modules": "modules_enabled"}.get(field, field)
			values[target] = ", ".join(info[field]) if isinstance(info[field], list) else info[field]
	frappe.db.set_single_value("AI Settings", values)

	new_status = values.get("license_status")
	if new_status and new_status != old_status:
		from abenext_ai.licensing import notify

		try:
			notify.status_changed(old_status, new_status, values.get("valid_till"))
		except Exception:
			frappe.log_error(title="Abenext AI: license notice failed")


@frappe.whitelist()
def license_status():
	"""Status shown in the warning banner on AI forms."""
	return frappe.db.get_single_value("AI Settings", "license_status")


@frappe.whitelist()
def test_connection():
	"""Check the license and the AI provider. System Manager only; sends no business data."""
	frappe.only_for("System Manager")
	try:
		result = process("ai.ping")
	except AIServerError as exc:
		# Keep the license status the server reported, even though this request ends in an error.
		frappe.db.commit()
		frappe.throw(str(exc), title=_("Connection failed"))
	frappe.db.commit()
	return result
