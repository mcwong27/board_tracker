import { type Html, html, raw } from "../html";
import type { Asset, Checkout, User } from "../types";

/** Available / Checked out / Retired badge. */
export function statusBadge(asset: Asset, active: Checkout | null): Html {
  if (asset.retired) return html`<span class="badge retired">Retired</span>`;
  if (!active) return html`<span class="badge available">Available</span>`;
  return html`<span class="badge out">Checked out</span>`;
}

export type ActionProps = {
  asset: Asset;
  active: Checkout | null;
  user: User | null;
  back: string;
  csrfToken: string;
};

/** Check out / return buttons for one asset. */
export function actionButtons({ asset, active, user, back, csrfToken }: ActionProps): Html {
  if (asset.retired) return html`<span class="muted">Retired</span>`;
  if (!active) {
    return html`<form class="inline" method="post" action="/assets/${asset.id}/checkout">
    <input type="hidden" name="csrf_token" value="${csrfToken}">
    <input type="hidden" name="back" value="${back}">
    <button>Check out</button>
  </form>`;
  }
  if (user && (active.user_email === user.email || user.isAdmin)) {
    return html`<form class="inline" method="post" action="/assets/${asset.id}/return">
    <input type="hidden" name="csrf_token" value="${csrfToken}">
    <input type="hidden" name="back" value="${back}">
    <button class="secondary">${active.user_email === user.email ? "Return" : "Force return"}</button>
  </form>`;
  }
  return html``;
}

/** A boolean attribute such as `selected`, emitted only when `on`. */
export function flag(on: boolean, name: "selected" | "disabled" | "checked"): Html {
  return on ? raw(name) : html``;
}
