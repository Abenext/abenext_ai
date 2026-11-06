// Copyright (c) 2026, Abenext. All rights reserved.
// Audit Watchdog dashboard: audit areas, findings and an assistant panel, all from real findings.

frappe.pages["watchdog-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Audit Watchdog"), single_column: true });
	new WatchdogDashboard(page, wrapper);
};

const M = "abenext_ai.watchdog.dashboard";
const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));

class WatchdogDashboard {
	constructor(page, wrapper) {
		this.page = page;
		this.area = null;
		this.selected = null;
		this.data = null;
		this.add_style();
		this.make_toolbar();
		this.$root = $(`<div class="abx-wd"></div>`).appendTo(page.body);
		this.refresh();
	}

	make_toolbar() {
		this.company = this.page.add_field({
			fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company",
			change: () => this.refresh(),
		});
		this.status = this.page.add_field({
			fieldname: "status", label: __("Status"), fieldtype: "Select", options: ["Open", "Fixed", "Ignored"], default: "Open",
			change: () => this.refresh(),
		});
		this.page.set_primary_action(__("Run Checks Now"), () => {
			frappe.call("abenext_ai.watchdog.runner.run_now").then(() => {
				frappe.show_alert({ message: __("Checks are running. This page refreshes in a minute."), indicator: "blue" });
				setTimeout(() => this.refresh(), 60000);
			});
		}, "refresh");
		this.page.set_secondary_action(__("Morning Report"), () => {
			frappe.call({ method: "abenext_ai.watchdog.report.preview_report", freeze: true }).then((r) => {
				const report = r.message || {};
				const d = new frappe.ui.Dialog({ title: __("Morning Report (preview, not sent)"), size: "large" });
				d.$body.html(`<div style="max-height:65vh;overflow:auto">${report.html || ""}${report.note ? `<p class="text-muted small">${esc(report.note)}</p>` : ""}</div>`);
				d.show();
			});
		});
		this.page.add_menu_item(__("Findings List"), () => frappe.set_route("List", "AI Watchdog Finding"));
		this.page.add_menu_item(__("Rules"), () => frappe.set_route("List", "AI Watchdog Rule"));
		this.page.add_menu_item(__("Settings"), () => frappe.set_route("Form", "AI Watchdog Settings"));
	}

	refresh() {
		frappe.call({
			method: `${M}.overview`,
			args: { company: this.company.get_value() || null, status: this.status.get_value() || "Open" },
		}).then((r) => {
			this.data = r.message;
			const still = this.data.findings.find((f) => f.name === (this.selected && this.selected.name));
			this.selected = still || this.visible()[0] || null;
			this.render();
		});
	}

	visible() {
		const all = (this.data && this.data.findings) || [];
		return this.area ? all.filter((f) => f.area === this.area) : all;
	}

	money(v) {
		return format_currency(v, frappe.defaults.get_default("currency"));
	}

	render() {
		const d = this.data;
		const status = this.status.get_value() || "Open";
		this.$root.html(`
			<div class="abx-wd-grid">
				<aside class="abx-wd-col">
					<div class="abx-wd-summary">
						<div class="abx-wd-big">${d.totals.count}</div>
						<div class="abx-wd-muted">${esc(__("{0} findings", [status.toLowerCase()]))}</div>
						<div class="abx-wd-pills">
							<span class="abx-pill high">${d.totals.high} ${esc(__("High"))}</span>
							<span class="abx-pill medium">${d.totals.medium} ${esc(__("Medium"))}</span>
						</div>
						<div class="abx-wd-muted small">${esc(__("Amount involved"))}: <b>${esc(this.money(d.totals.amount))}</b></div>
						${d.last_run ? `<div class="abx-wd-muted small">${esc(__("Last checked"))} ${esc(d.last_run)}</div>` : ""}
					</div>
					<div class="abx-wd-heading">${esc(__("Audit areas"))}</div>
					<div class="abx-area ${this.area ? "" : "active"}" data-area="">
						<span>${esc(__("All areas"))}</span><span class="abx-count">${d.totals.count}</span>
					</div>
					${d.areas.map((a) => {
						const total = a.High + a.Medium + a.Low;
						return `<div class="abx-area ${this.area === a.key ? "active" : ""}" data-area="${esc(a.key)}">
							<span>${frappe.utils.icon(a.icon, "sm")} ${esc(a.label)}</span>
							<span>${a.High ? `<span class="abx-pill high">${a.High}</span>` : ""}
								${a.Medium ? `<span class="abx-pill medium">${a.Medium}</span>` : ""}
								${!a.High && !a.Medium ? `<span class="abx-count">${total}</span>` : ""}</span>
						</div>`;
					}).join("")}
				</aside>
				<main class="abx-wd-col">
					<div class="abx-wd-heading">${esc(__("Findings"))} <span class="abx-wd-muted">· ${this.visible().length}</span></div>
					${this.visible().length ? this.visible().map((f) => this.card(f)).join("")
						: `<div class="abx-empty">${frappe.utils.icon("tick", "lg")}<div>${esc(status === "Open" ? __("Nothing needs attention here.") : __("No findings."))}</div></div>`}
				</main>
				<aside class="abx-wd-col abx-assistant"></aside>
			</div>`);
		this.$root.find(".abx-area").on("click", (e) => {
			this.area = $(e.currentTarget).attr("data-area") || null;
			this.selected = this.visible()[0] || null;
			this.render();
		});
		this.$root.find(".abx-card").on("click", (e) => {
			if ($(e.target).closest("a,button").length) return;
			this.selected = this.data.findings.find((f) => f.name === $(e.currentTarget).attr("data-name"));
			this.$root.find(".abx-card").removeClass("selected");
			$(e.currentTarget).addClass("selected");
			this.render_assistant();
		});
		this.$root.find("[data-action]").on("click", (e) => {
			const $b = $(e.currentTarget);
			frappe.call(`abenext_ai.watchdog.runner.set_status`, { names: [$b.attr("data-name")], status: $b.attr("data-action") })
				.then(() => this.refresh());
		});
		this.render_assistant();
	}

	card(f) {
		const sev = (f.severity || "Low").toLowerCase();
		const link = (label, doctype, name, url) => name
			? `<div><div class="abx-k">${esc(label)}</div><a href="${esc(url)}" class="abx-v">${esc(doctype)} ${esc(name)}</a></div>` : "";
		const open = f.status === "Open";
		return `<div class="abx-card ${sev} ${this.selected && this.selected.name === f.name ? "selected" : ""}" data-name="${esc(f.name)}">
			<div class="abx-card-head">
				<div class="abx-icon ${sev}">${frappe.utils.icon(sev === "high" ? "solid-error" : "solid-warning", "md")}</div>
				<div class="abx-card-title">
					<div class="abx-title">${esc(f.title)}</div>
					<div class="abx-wd-muted small">${esc(f.rule_name)}${f.company ? " · " + esc(f.company) : ""}</div>
				</div>
				<span class="abx-badge ${sev}">${esc(__(f.severity))}</span>
			</div>
			<div class="abx-facts">
				${link(__("Document"), f.reference_doctype, f.reference_name, f.reference_url)}
				${link(__("Related"), f.related_doctype, f.related_name, f.related_url)}
				${f.amount ? `<div><div class="abx-k">${esc(__("Amount"))}</div><div class="abx-v">${esc(this.money(f.amount))}</div></div>` : ""}
			</div>
			<div class="abx-issue ${sev}"><b>${esc(__("Issue"))}:</b> ${esc(f.details)}</div>
			${f.note ? `<div class="abx-wd-muted small">${esc(__("Note"))}: ${esc(f.note)}</div>` : ""}
			<div class="abx-card-foot">
				<span class="abx-wd-muted small">${frappe.utils.icon("calendar", "xs")} ${esc(__("Detected"))} ${esc(f.detected)}</span>
				<span>
					${open ? `<button class="btn btn-xs btn-primary" data-action="Fixed" data-name="${esc(f.name)}">${esc(__("Mark Fixed"))}</button>
						<button class="btn btn-xs btn-default" data-action="Ignored" data-name="${esc(f.name)}">${esc(__("Ignore"))}</button>`
						: `<button class="btn btn-xs btn-default" data-action="Open" data-name="${esc(f.name)}">${esc(__("Reopen"))}</button>`}
				</span>
			</div>
		</div>`;
	}

	render_assistant() {
		const $a = this.$root.find(".abx-assistant");
		const f = this.selected;
		if (!f) {
			$a.html(`<div class="abx-panel"><div class="abx-wd-muted">${esc(__("Select a finding to see why it matters and what to do."))}</div></div>`);
			return;
		}
		const list = (items, numbered) => items.length
			? `<${numbered ? "ol" : "ul"} class="abx-list">${items.map((i) => `<li>${esc(i)}</li>`).join("")}</${numbered ? "ol" : "ul"}>` : "";
		$a.html(`
			<div class="abx-panel">
				<div class="abx-panel-title">${frappe.utils.icon("star", "md")} ${esc(__("Assistant"))}</div>
				<div class="abx-wd-muted small">${esc(f.title)}</div>
				<div class="abx-box why"><div class="abx-box-title">${esc(__("Why this matters"))}</div>${list(f.why)}</div>
				<div class="abx-box act"><div class="abx-box-title">${esc(__("Recommended actions"))}</div>${list(f.actions, true)}</div>
				<div class="abx-ai"></div>
				<button class="btn btn-sm btn-default abx-explain" ${this.data.ai_available ? "" : "disabled"}>
					${frappe.utils.icon("star", "sm")} ${esc(__("Explain with AI"))}</button>
				${this.data.ai_available ? "" : `<div class="abx-wd-muted small">${esc(__("Needs Audit Watchdog AI on your Abenext license."))}</div>`}
			</div>
			<div class="abx-panel abx-history"><div class="abx-panel-title">${esc(__("History"))}</div><div class="abx-wd-muted small">${esc(__("Loading..."))}</div></div>`);
		$a.find(".abx-explain").on("click", () => {
			$a.find(".abx-ai").html(`<div class="abx-wd-muted small">${esc(__("Thinking..."))}</div>`);
			frappe.call({ method: `${M}.explain`, args: { name: f.name } }).then((r) => {
				const x = r.message || {};
				$a.find(".abx-ai").html(`<div class="abx-box ai"><div class="abx-box-title">${esc(__("AI analysis"))}</div>
					<p>${esc(x.summary || "")}</p>${list(x.why || [])}${(x.actions || []).length ? `<div class="abx-box-title">${esc(__("Suggested next steps"))}</div>${list(x.actions, true)}` : ""}</div>`);
			}, () => $a.find(".abx-ai").empty());
		});
		frappe.call({ method: `${M}.history`, args: { name: f.name } }).then((r) => {
			const h = r.message || {};
			const items = (h.resolved || []).map((x) => `<div class="abx-hist"><span class="abx-dot ${x.status === "Fixed" ? "ok" : "ign"}"></span>
				<div><div>${esc(x.title)}</div><div class="abx-wd-muted small">${esc(__(x.status))} ${esc(x.when)}${x.note ? " · " + esc(x.note) : ""}</div></div></div>`).join("");
			$a.find(".abx-history").html(`<div class="abx-panel-title">${esc(__("History"))}</div>
				<div class="abx-wd-muted small">${esc(__("{0} similar finding(s) resolved before.", [h.resolved_count || 0]))}
				${h.same_document ? esc(__(" This document appears in {0} other finding(s).", [h.same_document])) : ""}</div>${items}`);
		});
	}

	add_style() {
		if (document.getElementById("abx-wd-style")) return;
		$(`<style id="abx-wd-style">
			.abx-wd-grid { display: grid; grid-template-columns: 260px minmax(0, 1fr) 340px; gap: 20px; align-items: start; }
			@media (max-width: 1100px) { .abx-wd-grid { grid-template-columns: 1fr; } }
			.abx-wd-col { min-width: 0; }
			.abx-wd-heading { font-size: 12px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--text-muted); margin: 6px 0 12px; }
			.abx-wd-muted { color: var(--text-muted); }
			.abx-wd-summary { background: linear-gradient(135deg, #f97316, #ea580c); color: #fff; border-radius: 14px; padding: 18px; margin-bottom: 18px; }
			.abx-wd-summary .abx-wd-muted { color: rgba(255,255,255,.85); }
			.abx-wd-big { font-size: 34px; font-weight: 700; line-height: 1; }
			.abx-wd-pills { margin: 10px 0; display: flex; gap: 6px; }
			.abx-wd-summary .abx-pill { background: rgba(255,255,255,.22); color: #fff; }
			.abx-area { display: flex; justify-content: space-between; align-items: center; padding: 12px 14px; border: 1px solid var(--border-color);
				border-radius: 12px; margin-bottom: 8px; cursor: pointer; background: var(--card-bg); font-weight: 600; }
			.abx-area:hover { border-color: #f97316; }
			.abx-area.active { border-color: #f97316; box-shadow: 0 0 0 2px rgba(249,115,22,.25); }
			.abx-area svg { margin-right: 6px; }
			.abx-pill { display: inline-block; border-radius: 999px; padding: 1px 9px; font-size: 12px; font-weight: 600; }
			.abx-pill.high { background: rgba(220,38,38,.12); color: #dc2626; }
			.abx-pill.medium { background: rgba(217,119,6,.14); color: #b45309; }
			.abx-count { color: var(--text-muted); font-size: 12px; }
			.abx-card { border: 1px solid var(--border-color); border-radius: 14px; padding: 16px; margin-bottom: 14px; background: var(--card-bg); cursor: pointer; }
			.abx-card.high { border-color: rgba(220,38,38,.35); background: linear-gradient(0deg, rgba(220,38,38,.04), rgba(220,38,38,.04)), var(--card-bg); }
			.abx-card.medium { border-color: rgba(217,119,6,.35); background: linear-gradient(0deg, rgba(217,119,6,.05), rgba(217,119,6,.05)), var(--card-bg); }
			.abx-card.low { border-color: rgba(37,99,235,.3); background: linear-gradient(0deg, rgba(37,99,235,.04), rgba(37,99,235,.04)), var(--card-bg); }
			.abx-card.selected { box-shadow: 0 0 0 2px rgba(124,58,237,.45); }
			.abx-card-head { display: flex; gap: 12px; align-items: flex-start; }
			.abx-card-title { flex: 1; min-width: 0; }
			.abx-title { font-weight: 600; font-size: 15px; }
			.abx-icon { width: 36px; height: 36px; border-radius: 10px; display: flex; align-items: center; justify-content: center; flex: none; }
			.abx-icon.high { background: #dc2626; } .abx-icon.medium { background: #d97706; } .abx-icon.low { background: #2563eb; }
			.abx-icon svg { --icon-stroke: #fff; fill: #fff; stroke: #fff; }
			.abx-badge { border-radius: 999px; padding: 2px 10px; font-size: 11px; font-weight: 700; text-transform: uppercase; color: #fff; }
			.abx-badge.high { background: #dc2626; } .abx-badge.medium { background: #d97706; } .abx-badge.low { background: #2563eb; }
			.abx-facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; background: var(--card-bg);
				border: 1px solid var(--border-color); border-radius: 10px; padding: 12px; margin: 12px 0; }
			.abx-k { font-size: 12px; color: var(--text-muted); } .abx-v { font-weight: 600; word-break: break-word; }
			.abx-issue { border-radius: 10px; padding: 10px 12px; font-size: 13px; }
			.abx-issue.high { background: rgba(220,38,38,.1); color: var(--text-color); }
			.abx-issue.medium { background: rgba(217,119,6,.12); color: var(--text-color); }
			.abx-issue.low { background: rgba(37,99,235,.1); color: var(--text-color); }
			.abx-card-foot { display: flex; justify-content: space-between; align-items: center; margin-top: 12px; gap: 8px; flex-wrap: wrap; }
			.abx-empty { text-align: center; padding: 60px 20px; color: var(--text-muted); border: 1px dashed var(--border-color); border-radius: 14px; }
			.abx-panel { border: 1px solid var(--border-color); border-radius: 14px; padding: 16px; margin-bottom: 14px; background: var(--card-bg); }
			.abx-panel-title { font-weight: 700; font-size: 15px; margin-bottom: 6px; display: flex; gap: 6px; align-items: center; }
			.abx-box { border-radius: 10px; padding: 12px; margin: 12px 0; }
			.abx-box.why { background: rgba(124,58,237,.08); } .abx-box.act { background: rgba(249,115,22,.09); } .abx-box.ai { background: rgba(37,99,235,.08); }
			.abx-box-title { font-weight: 600; margin-bottom: 6px; }
			.abx-list { margin: 0; padding-left: 18px; } .abx-list li { margin-bottom: 4px; }
			.abx-hist { display: flex; gap: 10px; margin-top: 10px; }
			.abx-dot { width: 8px; height: 8px; border-radius: 50%; margin-top: 7px; flex: none; }
			.abx-dot.ok { background: #16a34a; } .abx-dot.ign { background: #d97706; }
		</style>`).appendTo("head");
	}
}
