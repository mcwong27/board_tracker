import { cloudflareTest } from "@cloudflare/vitest-plugin";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [
    cloudflareTest({
      wrangler: { configPath: "./wrangler.jsonc" },
      // wrangler.jsonc marks the D1 binding `remote`; tests must stay local so they
      // can never read or write the production database.
      remoteBindings: false,
      miniflare: {
        // Overrides wrangler.jsonc, where the DB binding is marked `remote`.
        // Tests must never touch the production database.
        d1Databases: { DB: "btrack-test" },
        // Each test file gets isolated storage; bindings mirror .dev.vars.
        bindings: {
          ENV: "development",
          DEV_LOGIN: "1",
          SECRET_KEY: "test-secret",
          BASE_URL: "http://localhost:8787",
        },
      },
    }),
  ],
  test: { globals: true },
});
