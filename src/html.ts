/**
 * Minimal HTML templating: a tagged template that escapes interpolations.
 *
 * Every value substituted into html`` is escaped unless it is already Html (the
 * result of another html`` call) or wrapped in raw(). That makes escaping the
 * default and un-escaping a visible, deliberate act.
 */

export class Html {
  constructor(readonly value: string) {}
  toString(): string {
    return this.value;
  }
}

/** Mark a string as already-safe HTML. Only for markup you constructed yourself. */
export function raw(value: string): Html {
  return new Html(value);
}

export function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

type Value = Html | string | number | boolean | null | undefined | Value[];

function render(value: Value): string {
  if (value === null || value === undefined || value === false) return "";
  if (value === true) return "";
  if (value instanceof Html) return value.value;
  if (Array.isArray(value)) return value.map(render).join("");
  return escapeHtml(String(value));
}

export function html(strings: TemplateStringsArray, ...values: Value[]): Html {
  let out = strings[0] ?? "";
  for (let i = 0; i < values.length; i++) {
    out += render(values[i]) + (strings[i + 1] ?? "");
  }
  return new Html(out);
}

/** Render a list with a separator, e.g. joining spans with ", ". */
export function join(parts: Value[], separator: string): Html {
  return raw(parts.map(render).join(escapeHtml(separator)));
}
