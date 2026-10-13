import { localDateTime } from "../dates";
import { type Html, html } from "../html";
import type { Asset, AssetType, Checkout, FpgaServer, FpgaType } from "../types";
import { type LayoutContext, layout } from "./layout";
import { actionButtons, flag, statusBadge } from "./partials";

export function adminPage(
  ctx: LayoutContext,
  props: {
    rows: Array<[Asset, Checkout | null]>;
    types: AssetType[];
    typeCounts: Map<number, number>;
    fpgaTypes: FpgaType[];
    fpgaServers: FpgaServer[];
    placements: Map<string, number>;
    error?: string | null;
  },
): Html {
  const { rows, types, typeCounts, fpgaTypes, fpgaServers, placements, error } = props;
  const csrf = html`<input type="hidden" name="csrf_token" value="${ctx.csrfToken}">`;
  const placed = (t: FpgaType, s: FpgaServer) => placements.get(`${t.id}:${s.id}`) ?? 0;

  const body = html`
<h1>Admin</h1>
${error ? html`<p class="banner error prewrap">${error}</p>` : ""}
<nav class="pills" aria-label="Admin sections">
  <a href="#assets">Assets</a>
  <a href="#asset-types">Asset types</a>
  <a href="#fpga-counts">FPGA counts</a>
  <a href="#fpga-types">FPGA types</a>
  <a href="#fpga-servers">Servers</a>
</nav>

<h2 id="assets">Assets</h2>
<div class="actions">
  <a class="button" href="/admin/assets/new">Add asset</a>
  <a href="/admin/export/assets.csv">Download assets CSV</a>
  <a href="/admin/export/checkouts.csv">Download checkout history CSV</a>
</div>
<details class="panel">
  <summary>Import assets from CSV</summary>
  <p class="muted">
    Same columns as the assets CSV above: <code>name</code> and <code>type</code> are required;
    <code>serial</code>, <code>chip_mounted</code>, <code>location</code>, <code>notes</code> and
    <code>retired</code> are optional. Any other column is ignored, so you can download the file,
    edit it, and upload it back. Rows are matched by name — existing assets are updated, new ones
    are created, and nothing is ever deleted. Missing types are created. If any row is bad the
    whole file is rejected.
  </p>
  <form method="post" action="/admin/assets/import" enctype="multipart/form-data" class="row">
    ${csrf}
    <input type="file" name="file" accept=".csv,text/csv" required>
    <button>Import</button>
  </form>
</details>
${
  rows.length
    ? html`<div class="table-wrap">
<table>
  <thead><tr><th>Asset</th><th>Type</th><th>Serial</th><th>Status</th><th>Holder</th><th></th></tr></thead>
  <tbody>
  ${rows.map(
    ([asset, active]) => html`<tr>
    <td><a href="/assets/${asset.id}">${asset.name}</a></td>
    <td>${asset.type.name}</td>
    <td>${asset.serial}</td>
    <td>${statusBadge(asset, active)}</td>
    <td>${active ? html`${active.user_email}<br><span class="muted">since ${localDateTime(active.checked_out_at)}</span>` : ""}</td>
    <td class="row">
      <a href="/admin/assets/${asset.id}/edit">Edit</a>
      ${active ? actionButtons({ asset, active, user: ctx.user, back: "/admin", csrfToken: ctx.csrfToken }) : ""}
      <form class="inline" method="post" action="/admin/assets/${asset.id}/${asset.retired ? "unretire" : "retire"}">
        ${csrf}
        <button class="secondary">${asset.retired ? "Restore" : "Retire"}</button>
      </form>
    </td>
  </tr>`,
  )}
  </tbody>
</table>
</div>`
    : html`<p class="muted">No assets yet.</p>`
}

<h2 id="asset-types">Asset types</h2>
<p class="muted">Track whatever you like: boards, instruments, cables, licences.</p>
${
  types.length
    ? html`<div class="table-wrap">
<table>
  <thead><tr><th>Type</th><th>Assets</th><th></th></tr></thead>
  <tbody>
  ${types.map((t) => {
    const n = typeCounts.get(t.id) ?? 0;
    return html`<tr>
    <td>
      <form class="row" method="post" action="/admin/types/${t.id}/rename">
        ${csrf}
        <input type="text" name="name" value="${t.name}" maxlength="100" required aria-label="Type name">
        <button class="secondary">Rename</button>
      </form>
    </td>
    <td>${n}</td>
    <td>
      <form class="inline" method="post" action="/admin/types/${t.id}/delete">
        ${csrf}
        <button class="secondary" ${flag(n > 0, "disabled")} ${n > 0 ? html`title="In use by ${n} asset(s)"` : ""}>Delete</button>
      </form>
    </td>
  </tr>`;
  })}
  </tbody>
</table>
</div>`
    : html`<p class="muted">No types yet. Add one before adding assets.</p>`
}
<form method="post" action="/admin/types" class="row add-form">
  ${csrf}
  <input type="text" name="name" placeholder="New type name" maxlength="100" required>
  <button>Add type</button>
</form>

<h2 id="fpga-counts">FPGA counts: how many, where</h2>
${
  fpgaTypes.length && fpgaServers.length
    ? html`<form method="post" action="/admin/fpga/counts">
  ${csrf}
  <div class="table-wrap">
  <table>
    <thead>
      <tr><th>FPGA type</th>${fpgaServers.map((s) => html`<th>${s.name}</th>`)}<th>Total</th></tr>
    </thead>
    <tbody>
    ${fpgaTypes.map(
      (t) => html`<tr>
      <td>${t.name}</td>
      ${fpgaServers.map(
        (s) => html`<td>
        <input class="qty" type="number" min="0" name="qty-${t.id}-${s.id}"
               value="${placed(t, s)}"
               aria-label="${t.name} in ${s.name}">
      </td>`,
      )}
      <td class="muted">${fpgaServers.reduce((sum, s) => sum + placed(t, s), 0)}</td>
    </tr>`,
    )}
    </tbody>
  </table>
  </div>
  <div class="row add-form"><button>Save counts</button></div>
</form>`
    : html`<p class="muted">Add at least one FPGA type and one server to fill in counts.</p>`
}

<h2 id="fpga-types">FPGA types</h2>
${
  fpgaTypes.length
    ? html`<div class="table-wrap">
<table>
  <thead><tr><th>Type</th><th></th></tr></thead>
  <tbody>
  ${fpgaTypes.map(
    (t) => html`<tr>
    <td>
      <form class="row" method="post" action="/admin/fpga/types/${t.id}/rename">
        ${csrf}
        <input type="text" name="name" value="${t.name}" maxlength="100" required aria-label="FPGA type name">
        <button class="secondary">Rename</button>
      </form>
    </td>
    <td>
      <form class="inline" method="post" action="/admin/fpga/types/${t.id}/delete">
        ${csrf}
        <button class="secondary">Delete</button>
      </form>
    </td>
  </tr>`,
  )}
  </tbody>
</table>
</div>`
    : html`<p class="muted">No FPGA types yet.</p>`
}
<form method="post" action="/admin/fpga/types" class="row add-form">
  ${csrf}
  <input type="text" name="name" placeholder="New FPGA type, e.g. U250" maxlength="100" required>
  <button>Add type</button>
</form>

<h2 id="fpga-servers">Servers</h2>
${
  fpgaServers.length
    ? html`<div class="table-wrap">
<table>
  <thead><tr><th>Server</th><th>Notes</th><th></th></tr></thead>
  <tbody>
  ${fpgaServers.map(
    (s) => html`<tr>
    <td>
      <form class="row" method="post" action="/admin/fpga/servers/${s.id}/rename">
        ${csrf}
        <input type="text" name="name" value="${s.name}" maxlength="100" required aria-label="Server name">
        <button class="secondary">Rename</button>
      </form>
    </td>
    <td class="prewrap muted">${s.notes}</td>
    <td>
      <form class="inline" method="post" action="/admin/fpga/servers/${s.id}/delete">
        ${csrf}
        <button class="secondary">Delete</button>
      </form>
    </td>
  </tr>`,
  )}
  </tbody>
</table>
</div>`
    : html`<p class="muted">No servers yet.</p>`
}
<form method="post" action="/admin/fpga/servers" class="row add-form">
  ${csrf}
  <input type="text" name="name" placeholder="New server, e.g. rack2-srv1" maxlength="100" required>
  <input type="text" name="notes" placeholder="Notes (optional)" maxlength="500">
  <button>Add server</button>
</form>
`;
  return layout({ ...ctx, title: "Admin" }, body);
}
