import { type Html, html } from "../html";
import type { Asset, AssetType } from "../types";
import { type LayoutContext, layout } from "./layout";
import { flag } from "./partials";

export function assetFormPage(
  ctx: LayoutContext,
  props: { asset: Asset | null; values: Record<string, string>; types: AssetType[]; error?: string | null },
): Html {
  const { asset, values, types, error } = props;
  const heading = asset ? `Edit ${asset.name}` : "Add asset";
  const body = html`
<h1>${heading}</h1>
${error ? html`<p class="banner error">${error}</p>` : ""}
<form method="post" class="stack"
      action="${asset ? `/admin/assets/${asset.id}/edit` : "/admin/assets/new"}">
  <input type="hidden" name="csrf_token" value="${ctx.csrfToken}">
  <label>Name <input type="text" name="name" value="${values.name}" maxlength="200" required autofocus></label>
  <label>Type
    <select name="type_id" required>
      <option value="">Choose…</option>
      ${types.map((t) => html`<option value="${t.id}" ${flag(values.type_id === String(t.id), "selected")}>${t.name}</option>`)}
    </select>
  </label>
  <label>Serial <input type="text" name="serial" value="${values.serial}" maxlength="200"></label>
  <label>Chip mounted <input type="text" name="chip_mounted" value="${values.chip_mounted}" maxlength="200"></label>
  <label>Location <input type="text" name="location" value="${values.location}" maxlength="200"></label>
  <label>Notes <textarea name="notes" rows="4">${values.notes}</textarea></label>
  <div class="row">
    <button>${asset ? "Save" : "Add asset"}</button>
    <a href="${asset ? `/assets/${asset.id}` : "/admin"}">Cancel</a>
  </div>
</form>
`;
  return layout({ ...ctx, title: heading }, body);
}
