// Secrets are set with `wrangler secret put`, so they aren't in wrangler.jsonc and
// `wrangler types` can't see them. Declare them alongside the generated bindings.
interface SecretBindings {
  GOOGLE_CLIENT_SECRET: string;
  GOOGLE_SERVICE_ACCOUNT_JSON: string;
}
interface Env extends SecretBindings {}
declare namespace Cloudflare {
  interface Env extends SecretBindings {}
}
