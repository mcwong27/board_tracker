# Google OAuth client setup

The app signs people in with Google. You need an OAuth client ID and secret.

1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and create a project (or
   pick an existing one), for example "Lab Board Tracker".
2. Open **APIs & Services → OAuth consent screen** (shown as **Google Auth Platform** in newer
   consoles) and click **Get started**.
   - **App name:** Lab Board Tracker. **Support email:** yours.
   - **Audience:** choose **Internal** if the project belongs to the berkeley.edu organization.
     Otherwise choose **External**. That's fine because the app itself rejects non-Berkeley
     accounts.
   - **Contact email:** yours. Agree to the policy and create the screen.
3. For an **External** app: under **Audience**, click **Publish app** to move it from Testing to
   In production. The app only requests `openid email profile`, so Google doesn't need to verify
   it. While it's still in Testing, only listed test users can sign in.
4. Open **Clients** (or **Credentials → Create credentials → OAuth client ID**):
   - **Application type:** Web application
   - **Authorized JavaScript origins:** the origin of your `BASE_URL`, e.g.
     `https://boards.example.berkeley.edu`
   - **Authorized redirect URIs:** `BASE_URL` + `/auth/callback`, e.g.
     `https://boards.example.berkeley.edu/auth/callback`. Also add
     `http://localhost:8787/auth/callback` if you want to test real sign-in locally.
5. Click **Create**. The **Client ID** goes in `wrangler.jsonc` under `vars` as
   `GOOGLE_CLIENT_ID`; the **Client secret** is a secret:
   `npx wrangler secret put GOOGLE_CLIENT_SECRET`. Locally both live in `.dev.vars`.

If sign-in fails with `redirect_uri_mismatch`, the redirect URI in the console must match
`BASE_URL/auth/callback` exactly, including scheme, host, path, and no trailing slash.

## Testing real sign-in locally

Put your OAuth credentials in `.dev.vars` with `ENV=development`, `DEV_LOGIN=0` and
`BASE_URL=http://localhost:8787`, add `http://localhost:8787/auth/callback` to the
client's authorized redirect URIs, then run:

```sh
npm run dev
```

Real sign-in also needs the Cloud Identity setup from
[Google Groups setup](google-groups.md), since group membership gates access. For most
local work, leave `DEV_LOGIN=1` and skip both.
