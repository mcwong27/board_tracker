import { longDate } from "../dates";
import { type Html, html, join } from "../html";
import type { Bar, FpgaReservation, Timeline } from "../types";
import { type LayoutContext, layout } from "./layout";

/** Plain decimal for inline styles (no exponent notation, no float noise). */
function pct(n: number): string {
  return String(Number(n.toFixed(4)));
}

function barLink(bar: Bar, thin: boolean): Html {
  const r = bar.reservation;
  const style = `left: ${pct(bar.left_pct)}%; width: ${pct(bar.width_pct)}%${bar.hue !== null ? `; --hue: ${bar.hue}` : ""}`;
  return html`<a class="timeline-bar${bar.over ? " over" : ""}${thin ? " thin" : ""}"
   style="${style}"
   href="/fpga/${r.id}/edit">
  ${!thin ? html`<span class="timeline-bar-text">${r.project}${r.quantity > 1 ? html` &times;${r.quantity}` : ""}</span>` : ""}
  <span class="tooltip">
    <strong>${r.project}</strong>
    <span class="tooltip-row"><span class="muted">FPGA</span> ${r.fpga_type.name} &times;${r.quantity}</span>
    <span class="tooltip-row"><span class="muted">Server</span> ${r.server ? r.server.name : "not recorded"}</span>
    <span class="tooltip-row"><span class="muted">Contact</span> ${r.contact}</span>
    <span class="tooltip-row"><span class="muted">Dates</span> ${longDate(r.start_date)} &ndash; ${longDate(r.end_date)}</span>
    ${r.special_requests ? html`<span class="tooltip-row"><span class="muted">Requests</span> ${r.special_requests}</span>` : ""}
    ${bar.over ? html`<span class="tooltip-row over-note">Over the number installed in that server.</span>` : ""}
    <span class="tooltip-row muted">Booked by ${r.created_by_email}</span>
  </span>
</a>`;
}

export function fpgaPage(
  ctx: LayoutContext,
  props: {
    timeline: Timeline;
    reservations: FpgaReservation[];
    windowStart: string;
    windowEnd: string;
    prevStart: string;
    nextStart: string;
    todayStart: string;
    error?: string | null;
  },
): Html {
  const { timeline, reservations, error } = props;
  const { groups, ticks, warnings } = timeline;
  const isAdmin = ctx.user?.isAdmin === true;

  const body = html`
<div class="row" style="justify-content: space-between">
  <h1>FPGA reservations</h1>
  <div class="row">
    ${isAdmin ? html`<a href="/admin">Manage inventory</a>` : ""}
    <a class="button" href="/fpga/new">Add reservation</a>
  </div>
</div>
${error ? html`<p class="banner error">${error}</p>` : ""}
${
  warnings.length
    ? html`<div class="banner warn">
  <strong>Over-subscribed:</strong>
  <ul class="tight">${warnings.map((w) => html`<li>${w}</li>`)}</ul>
  Sort it out with the other people holding those slots, or move to another server.
</div>`
    : ""
}

<div class="row timeline-nav" style="justify-content: space-between">
  <a href="/fpga?start=${props.prevStart}">&larr; Earlier</a>
  <span class="muted">${longDate(props.windowStart)} &ndash; ${longDate(props.windowEnd)}</span>
  <div class="row">
    <a href="/fpga?start=${props.todayStart}">Today</a>
    <a href="/fpga?start=${props.nextStart}">Later &rarr;</a>
  </div>
</div>

<div class="timeline">
  <div class="timeline-grid">
    <div class="tl-row timeline-head">
      <div class="tl-label"></div>
      <div class="tl-track">
        ${ticks.map((t) => html`<span class="timeline-tick" style="left: ${pct(t.left_pct)}%">${t.label}</span>`)}
      </div>
    </div>
    <div class="timeline-body">
      ${
        timeline.today_pct !== null
          ? html`<div class="timeline-today" style="left: calc(var(--gutter) + (100% - var(--gutter)) * ${(timeline.today_pct / 100).toFixed(4)})"></div>`
          : ""
      }
      ${groups.map(
        (group) => html`<details class="timeline-group">
        <summary class="tl-row">
          <div class="tl-label">
            <span class="caret" aria-hidden="true"></span>
            <span>
              ${group.fpga_type.name}
              <span class="muted small">${group.installed.length ? html`${group.total} installed` : "none installed"}</span>
            </span>
          </div>
          <div class="tl-track">
            <div class="timeline-mux">
              ${group.rows.map((row) => html`<div class="mux-band">${row.bars.map((bar) => barLink(bar, true))}</div>`)}
              ${group.rows.length ? "" : html`<div class="mux-band"></div>`}
            </div>
          </div>
        </summary>
        ${
          group.rows.length
            ? group.rows.map(
                (row) => html`<div class="tl-row slot-row">
            <div class="tl-label small${row.over_row ? " over-note" : ""}">
              ${row.hue !== null ? html`<span class="swatch" style="--hue: ${row.hue}"></span>` : ""}
              ${row.label}
            </div>
            <div class="tl-track">
              <div class="timeline-lane">${row.bars.map((bar) => barLink(bar, false))}</div>
            </div>
          </div>`,
              )
            : html`<div class="tl-row slot-row">
          <div class="tl-label small muted">No boards recorded</div>
          <div class="tl-track"><div class="timeline-lane"></div></div>
        </div>`
        }
        <div class="tl-row slot-row">
          <div class="tl-label small muted">Installed</div>
          <div class="tl-track installed-note muted small">
            ${
              group.installed.length
                ? join(
                    group.installed.map(([server, qty]) => html`${server.name} &times;${qty}`),
                    ", ",
                  )
                : html`Nothing recorded yet${isAdmin ? html` — <a href="/admin">add counts</a>` : ""}.`
            }
          </div>
        </div>
      </details>`,
      )}
    </div>
  </div>
</div>
${
  groups.length
    ? ""
    : html`<p class="muted">No FPGA types yet.${isAdmin ? html` <a href="/admin">Add some</a>.` : ""}</p>`
}

<h2>All reservations</h2>
${
  reservations.length
    ? html`<div class="table-wrap">
<table>
  <thead><tr><th>Type</th><th>Server</th><th>Project</th><th>Qty</th><th>Contact</th><th>Start</th><th>End</th><th>Special requests</th><th></th></tr></thead>
  <tbody>
  ${reservations.map(
    (r) => html`<tr>
    <td>${r.fpga_type.name}</td>
    <td>${r.server ? r.server.name : "—"}</td>
    <td>${r.project}</td>
    <td>${r.quantity}</td>
    <td>${r.contact}</td>
    <td>${r.start_date}</td>
    <td>${r.end_date}</td>
    <td class="prewrap">${r.special_requests}</td>
    <td class="row">
      ${
        ctx.user && (r.created_by_email === ctx.user.email || ctx.user.isAdmin)
          ? html`<a href="/fpga/${r.id}/edit">Edit</a>
      <form class="inline" method="post" action="/fpga/${r.id}/delete">
        <input type="hidden" name="csrf_token" value="${ctx.csrfToken}">
        <button class="secondary">Delete</button>
      </form>`
          : ""
      }
    </td>
  </tr>`,
  )}
  </tbody>
</table>
</div>`
    : html`<p class="muted">No FPGA reservations yet.</p>`
}
`;
  return layout({ ...ctx, title: "FPGA reservations" }, body);
}
