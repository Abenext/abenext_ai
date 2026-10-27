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
		reason = data.get("error") or _("The Abenext server returned an error (HTTP {0}).").format(response.status_code)
		raise AIServerError(reason)
	_remember_license(data.get("license") or {})
	return data.get("result") or {}


def _remember_license(info):
	if not info:
		return
	values = {"last_sync": now_datetime()}
	for field in ("status", "valid_till", "modules"):
		if field in info:
			target = {"status": "license_status", "modules": "modules_enabled"}.get(field, field)
			values[target] = ", ".join(info[field]) if isinstance(info[field], list) else info[field]
	frappe.db.set_single_value("AI Settings", values)


@frappe.whitelist()
def test_connection():
	"""Check the license and the AI provider. System Manager only; sends no business data."""
	frappe.only_for("System Manager")
	try:
		result = process("ai.ping")
	except AIServerError as exc:
		frappe.throw(str(exc), title=_("Connection failed"))
	frappe.db.commit()
	return result
