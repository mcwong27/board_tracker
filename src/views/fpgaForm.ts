import { type Html, html } from "../html";
import { join } from "../html";
import type { FpgaReservation, FpgaServer, FpgaType } from "../types";
import { type LayoutContext, layout } from "./layout";
import { flag } from "./partials";

export function fpgaFormPage(
  ctx: LayoutContext,
  props: {
    reservation: FpgaReservation | null;
    values: Record<string, string>;
    types: FpgaType[];
    servers: FpgaServer[];
    inventory: Map<number, Array<[FpgaServer, number]>>;
    error?: string | null;
  },
): Html {
  const { reservation, values, types, servers, inventory, error } = props;
  const heading = reservation ? "Edit reservation" : "Add FPGA reservation";
  const missing =
    !types.length && !servers.length
      ? "No FPGA types or servers have been set up yet."
      : !types.length
        ? "No FPGA types have been set up yet."
        : "No servers have been set up yet.";
  const body = html`
<h1>${heading}</h1>
${error ? html`<p class="banner error">${error}</p>` : ""}
${
  !types.length || !servers.length
    ? html`<p class="banner warn">
  ${missing}
  An admin needs to add them first.
</p>`
    : ""
}
<form method="post" class="stack"
      action="${reservation ? `/fpga/${reservation.id}/edit` : "/fpga/new"}">
  <input type="hidden" name="csrf_token" value="${ctx.csrfToken}">
  <label>FPGA type
    <select name="fpga_type_id" required>
      <option value="">Choose…</option>
      ${types.map((t) => html`<option value="${t.id}" ${flag(values.fpga_type_id === String(t.id), "selected")}>${t.name}</option>`)}
    </select>
  </label>
  <label>Server
    <select name="server_id" required>
      <option value="">Choose…</option>
      ${servers.map((s) => html`<option value="${s.id}" ${flag(values.server_id === String(s.id), "selected")}>${s.name}</option>`)}
    </select>
  </label>
  <label>Project <input type="text" name="project" value="${values.project}" maxlength="200" required autofocus></label>
  <label>Number of FPGAs <input type="number" name="quantity" value="${values.quantity}" min="1" required></label>
  <label>Username / point of contact <input type="text" name="contact" value="${values.contact}" maxlength="200" required></label>
  <label>Special requests <textarea name="special_requests" rows="3" placeholder="e.g. requires QSFP between two FPGAs">${values.special_requests}</textarea></label>
  <label>Start date <input type="date" name="start_date" value="${values.start_date}" required></label>
  <label>End date <input type="date" name="end_date" value="${values.end_date}" required></label>
  <div class="row">
    <button>${reservation ? "Save" : "Add reservation"}</button>
    <a href="/fpga">Cancel</a>
  </div>
</form>

${
  inventory.size
    ? html`<h2>What's installed where</h2>
<div class="table-wrap">
<table>
  <thead><tr><th>FPGA type</th><th>Servers</th></tr></thead>
  <tbody>
  ${types.map((t) => {
    const placed = inventory.get(t.id);
    if (!placed?.length) return "";
    return html`<tr>
    <td>${t.name}</td>
    <td>${join(
      placed.map(([server, qty]) => html`${server.name} &times;${qty}`),
      ", ",
    )}</td>
  </tr>`;
  })}
  </tbody>
</table>
</div>
<p class="muted">Booking more than a server holds is allowed — the timeline just flags it.</p>`
    : ""
}
`;
  return layout({ ...ctx, title: heading }, body);
}
