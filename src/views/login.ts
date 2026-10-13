import { type Html, html } from "../html";
import { type LayoutContext, layout } from "./layout";

export function loginPage(ctx: LayoutContext, props: { error?: string | null }): Html {
  const body = html`
<section class="narrow">
  <h1>Sign in</h1>
  <p>Use your @berkeley.edu Google account.</p>
  ${props.error ? html`<p class="banner error">${props.error}</p>` : ""}
  ${
    ctx.devLogin
      ? html`<a class="button" href="/dev-login">Dev login</a>`
      : html`<a class="button" href="/login/google">Sign in with Google</a>`
  }
</section>
`;
  return layout({ ...ctx, title: "Sign in" }, body);
}

export function devLoginPage(ctx: LayoutContext, props: { error?: string | null; email?: string }): Html {
  const body = html`
<section class="narrow">
  <h1>Dev login</h1>
  <p>Local testing only. Any @berkeley.edu address is accepted without a password.</p>
  ${props.error ? html`<p class="banner error">${props.error}</p>` : ""}
  <form method="post" action="/dev-login" class="stack">
    <input type="hidden" name="csrf_token" value="${ctx.csrfToken}">
    <label>Email <input type="email" name="email" value="${props.email ?? ""}" required autofocus></label>
    <label>Name <input type="text" name="name"></label>
    <label><input type="checkbox" name="admin"> Sign in as admin (dev only; replaces the real admins group)</label>
    <button>Sign in</button>
  </form>
</section>
`;
  return layout({ ...ctx, title: "Dev login" }, body);
}
