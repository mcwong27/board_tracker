# Google OAuth client setup

The app signs people in with Google. You need an OAuth client ID and secret for `.env`.

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
     `http://localhost:8000/auth/callback` if you want to test real sign-in locally. If `BASE_URL`
     has a path prefix, the redirect URI includes it: `https://host/boards/auth/callback`.
5. Click **Create** and copy the **Client ID** and **Client secret** into `.env` as
   `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.

If sign-in fails with `redirect_uri_mismatch`, the redirect URI in the console must match
`BASE_URL/auth/callback` exactly, including scheme, host, path, and no trailing slash.

## Testing real sign-in locally

Put your OAuth credentials in `.env` with `ENV=development`, `DEV_LOGIN=0` and
`BASE_URL=http://localhost:8000`, then run:

```sh
uv run --env-file .env uvicorn --factory app.main:create_app --reload
```
