import { Hono } from "hono";

const app = new Hono<{ Bindings: Env }>();

app.get("/healthz", (c) => c.text("ok"));

export default app;
