import { localDateTime } from "../dates";
import { type Html, html } from "../html";
import type { Asset, Checkout } from "../types";
import { type LayoutContext, layout } from "./layout";
import { actionButtons, statusBadge } from "./partials";

export function assetPage(
  ctx: LayoutContext,
  props: { asset: Asset; active: Checkout | null; history: Checkout[]; error?: string | null },
): Html {
  const { asset, active, history, error } = props;
  const back = `/assets/${asset.id}`;
  const body = html`
<div class="row">
  <h1>${asset.name}</h1>
  ${statusBadge(asset, active)}
  ${ctx.user?.isAdmin ? html`<a href="/admin/assets/${asset.id}/edit">Edit</a>` : ""}
</div>
${error ? html`<p class="banner error">${error}</p>` : ""}

<dl class="details">
  <dt>Type</dt><dd>${asset.type.name}</dd>
  <dt>Serial</dt><dd>${asset.serial || "—"}</dd>
  <dt>Chip mounted</dt><dd>${asset.chip_mounted || "—"}</dd>
  <dt>Location</dt><dd>${asset.location || "—"}</dd>
  ${asset.notes ? html`<dt>Notes</dt><dd class="prewrap">${asset.notes}</dd>` : ""}
  ${
    active
      ? html`<dt>Held by</dt><dd>${active.user_name} &lt;${active.user_email}&gt; since ${localDateTime(active.checked_out_at)}</dd>
  ${active.notes ? html`<dt>Checkout note</dt><dd class="prewrap">${active.notes}</dd>` : ""}`
      : ""
  }
</dl>

${
  !asset.retired && !active
    ? html`<h2>Check out</h2>
<form method="post" action="/assets/${asset.id}/checkout" class="stack">
  <input type="hidden" name="csrf_token" value="${ctx.csrfToken}">
  <label>Note (optional) <input type="text" name="notes" maxlength="500" placeholder="e.g. for the lab 3 demo"></label>
  <div><button>Check out ${asset.name}</button></div>
</form>`
    : active
      ? html`<p>${actionButtons({ asset, active, user: ctx.user, back, csrfToken: ctx.csrfToken })}</p>`
      : ""
}

<h2>History</h2>
${
  history.length
    ? html`<div class="table-wrap">
<table>
  <thead><tr><th>Who</th><th>Checked out</th><th>Returned</th><th>Note</th></tr></thead>
  <tbody>
  ${history.map(
    (c) => html`<tr>
    <td>${c.user_name || c.user_email}<br><span class="muted">${c.user_email}</span></td>
    <td>${localDateTime(c.checked_out_at)}</td>
    <td>${
      c.returned_at
        ? html`${localDateTime(c.returned_at)}${c.returned_by && c.returned_by !== c.user_email ? html`<br><span class="muted">by ${c.returned_by}</span>` : ""}`
        : html`<span class="badge out">Out</span>`
    }</td>
    <td class="prewrap">${c.notes}</td>
  </tr>`,
  )}
  </tbody>
</table>
</div>`
    : html`<p class="muted">Never checked out.</p>`
}
`;
  return layout({ ...ctx, title: asset.name }, body);
}
