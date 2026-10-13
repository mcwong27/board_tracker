import { localDateTime } from "../dates";
import { type Html, html } from "../html";
import type { Asset, AssetType, Checkout } from "../types";
import { type LayoutContext, layout } from "./layout";
import { actionButtons, statusBadge } from "./partials";

export function assetOverviewPage(
  ctx: LayoutContext,
  props: {
    rows: Array<[Asset, Checkout | null]>;
    types: AssetType[];
    selectedType: number | null;
    available: number;
  },
): Html {
  const { rows, types, selectedType, available } = props;
  const back = `/assets${selectedType ? `?type=${selectedType}` : ""}`;
  const current = (on: boolean) => (on ? html`aria-current="page"` : "");
  const body = html`
<div class="row" style="justify-content: space-between">
  <h1>Asset overview</h1>
  <span class="muted">${available} of ${rows.length} available</span>
</div>
<nav class="pills" aria-label="Filter by type">
  <a href="/assets" ${current(selectedType === null)}>All</a>
  ${types.map((t) => html`<a href="/assets?type=${t.id}" ${current(selectedType === t.id)}>${t.name}</a>`)}
</nav>
${
  rows.length
    ? html`<div class="table-wrap">
<table>
  <thead><tr><th>Asset</th><th>Type</th><th>Chip</th><th>Location</th><th>Status</th><th>Holder</th><th>Since</th><th></th></tr></thead>
  <tbody>
  ${rows.map(
    ([asset, active]) => html`<tr>
    <td><a href="/assets/${asset.id}">${asset.name}</a></td>
    <td>${asset.type.name}</td>
    <td>${asset.chip_mounted}</td>
    <td>${asset.location}</td>
    <td>${statusBadge(asset, active)}</td>
    <td>${active ? html`${active.user_name || active.user_email}${active.user_name && active.user_name !== active.user_email ? html`<br><span class="muted">${active.user_email}</span>` : ""}` : ""}</td>
    <td>${active ? localDateTime(active.checked_out_at) : ""}</td>
    <td>${actionButtons({ asset, active, user: ctx.user, back, csrfToken: ctx.csrfToken })}</td>
  </tr>`,
  )}
  </tbody>
</table>
</div>`
    : html`<p class="muted">No assets yet.${ctx.user?.isAdmin ? html` <a href="/admin/assets/new">Add one</a>.` : ""}</p>`
}
`;
  return layout({ ...ctx, title: "Asset overview" }, body);
}
