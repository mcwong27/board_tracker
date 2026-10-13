import { type Html, html } from "../html";
import { type LayoutContext, layout } from "./layout";

export function errorPage(ctx: LayoutContext, props: { message: string }): Html {
  const body = html`
<section class="narrow">
  <h1>${props.message}</h1>
  <p><a href="/">Back to your dashboard</a></p>
</section>
`;
  return layout({ ...ctx, title: "Error" }, body);
}
