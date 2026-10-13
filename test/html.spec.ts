import { describe, expect, it } from "vitest";
import { escapeHtml, html, join, raw } from "../src/html";

describe("html templating", () => {
  it("escapes interpolated values by default", () => {
    const name = '<script>alert("x")</script>';
    expect(html`<p>${name}</p>`.toString()).toBe(
      "<p>&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;</p>",
    );
  });

  it("escapes quotes so attribute injection fails", () => {
    const value = '" onerror="alert(1)';
    const out = html`<img alt="${value}">`.toString();
    expect(out).toBe('<img alt="&quot; onerror=&quot;alert(1)">');
  });

  it("does not double-escape nested templates", () => {
    const inner = html`<b>${"a & b"}</b>`;
    expect(html`<p>${inner}</p>`.toString()).toBe("<p><b>a &amp; b</b></p>");
  });

  it("renders arrays by concatenation", () => {
    const items = ["a", "<b>"].map((i) => html`<li>${i}</li>`);
    expect(html`<ul>${items}</ul>`.toString()).toBe("<ul><li>a</li><li>&lt;b&gt;</li></ul>");
  });

  it("drops null, undefined and false so conditionals are easy", () => {
    expect(html`<p>${null}${undefined}${false}</p>`.toString()).toBe("<p></p>");
  });

  it("renders numbers", () => {
    expect(html`<p>${42}</p>`.toString()).toBe("<p>42</p>");
  });

  it("raw() opts out of escaping", () => {
    expect(html`<p>${raw("<b>x</b>")}</p>`.toString()).toBe("<p><b>x</b></p>");
  });

  it("join escapes the parts but not the separator", () => {
    expect(join(["a<", "b"], ", ").toString()).toBe("a&lt;, b");
  });

  it("escapeHtml covers the five dangerous characters", () => {
    expect(escapeHtml(`&<>"'`)).toBe("&amp;&lt;&gt;&quot;&#39;");
  });
});
