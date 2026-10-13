import { localDateTime } from "../dates";
import { type Html, html } from "../html";
import type { Checkout } from "../types";
import { type LayoutContext, layout } from "./layout";
import { actionButtons } from "./partials";

export function dashboardPage(ctx: LayoutContext, props: { current: Checkout[]; past: Checkout[] }): Html {
  const { current, past } = props;
  const body = html`
<h1>Dashboard</h1>

<h2>Assets you have out</h2>
${
  current.length
    ? html`<div class="table-wrap">
<table>
  <thead><tr><th>Asset</th><th>Type</th><th>Since</th><th>Note</th><th></th></tr></thead>
  <tbody>
  ${current.map((c) => {
    const a = c.asset;
    return html`<tr>
    <td>${a ? html`<a href="/assets/${a.id}">${a.name}</a>` : ""}</td>
    <td>${a?.type?.name}</td>
    <td>${localDateTime(c.checked_out_at)}</td>
    <td class="prewrap">${c.notes}</td>
    <td>${a ? actionButtonsFor(ctx, c, a.id, a.name) : ""}</td>
  </tr>`;
  })}
  </tbody>
</table>
</div>`
    : html`<p class="muted">You don't have any assets checked out. <a href="/assets">Browse the asset overview</a>.</p>`
}

${
  past.length
    ? html`<h2>Past checkouts</h2>
<div class="table-wrap">
<table>
  <thead><tr><th>Asset</th><th>Checked out</th><th>Returned</th></tr></thead>
  <tbody>
  ${past.map(
    (c) => html`<tr>
    <td>${c.asset ? html`<a href="/assets/${c.asset.id}">${c.asset.name}</a>` : ""}</td>
    <td>${localDateTime(c.checked_out_at)}</td>
    <td>${localDateTime(c.returned_at)}</td>
  </tr>`,
  )}
  </tbody>
</table>
</div>`
    : ""
}
`;
  return layout({ ...ctx, title: "Dashboard" }, body);
}

/** The dashboard only has the checkout's embedded asset summary, which is all the buttons need. */
function actionButtonsFor(ctx: LayoutContext, c: Checkout, id: number, name: string): Html {
  return actionButtons({
    asset: {
      id,
      name,
      type_id: c.asset?.type?.id ?? 0,
      type: c.asset?.type ?? { id: 0, name: "" },
      serial: "",
      chip_mounted: "",
      location: "",
      notes: "",
      retired: false,
      created_at: "",
    },
    active: c,
    user: ctx.user,
    back: "/",
    csrfToken: ctx.csrfToken,
  });
}
