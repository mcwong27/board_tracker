import { type Html, html, raw } from "../html";
import type { User } from "../types";

export type LayoutContext = {
  title: string;
  user: User | null;
  devLogin: boolean;
  csrfToken: string;
  flash?: { message: string; kind: string } | null;
};

const THEME_SCRIPT = `
    // Applied before first paint so an explicit choice doesn't flash the other theme.
    try {
      var saved = localStorage.getItem("theme");
      if (saved === "light" || saved === "dark") {
        document.documentElement.setAttribute("data-theme", saved);
      }
    } catch (e) {}
  `;

export function layout(ctx: LayoutContext, body: Html): Html {
  const { user } = ctx;
  return html`<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${ctx.title} · bTrack</title>
  <link rel="stylesheet" href="/static/style.css">
  <script>${raw(THEME_SCRIPT)}</script>
</head>
<body>
<header class="topbar">
  <a class="brand" href="/">bTrack</a>
  ${
    user
      ? html`<nav>
    <a href="/">Dashboard</a>
    <a href="/assets">Asset overview</a>
    <a href="/fpga">FPGA reservations</a>
    ${user.isAdmin ? html`<a href="/admin">Admin</a>` : ""}
  </nav>
  <form class="whoami" method="post" action="/logout">
    <input type="hidden" name="csrf_token" value="${ctx.csrfToken}">
    <button class="theme-toggle" type="button" id="theme-toggle" aria-live="polite">Theme</button>
    <span>${user.email}</span>
    <button class="link">Sign out</button>
  </form>`
      : html`<button class="theme-toggle push-right" type="button" id="theme-toggle" aria-live="polite">Theme</button>`
  }
</header>
<main>
  ${ctx.devLogin ? html`<p class="banner warn">Dev login is on. Don't use this in production.</p>` : ""}
  ${ctx.flash ? html`<p class="banner ${ctx.flash.kind}">${ctx.flash.message}</p>` : ""}
  ${body}
</main>
<script src="/static/app.js"></script>
</body>
</html>
`;
}
