# Google Groups access control setup

The app has no built-in admin list. Instead, two Google Groups decide who can use it:

- **Users group** — membership is required to sign in at all (on top of the existing
  `@berkeley.edu` checks).
- **Admins group** — membership grants admin rights.

A small Google Cloud service account reads *direct* membership of these groups through the
Cloud Identity Groups API. You do **not** need to be a Google Workspace super admin to set this
up: adding the service account as an **Owner** or **Manager** of a Google Group through the
normal groups.google.com UI is enough to grant it API access to that group's membership, with no
domain-wide delegation.

## 1. Create a Google Cloud project

1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and create a project (or
   reuse the one from [Google OAuth setup](google-oauth.md)), for example "Lab Board Tracker".

## 2. Enable the Cloud Identity API

1. Open **APIs & Services → Library**.
2. Search for **Cloud Identity API** and click **Enable**.

## 3. Create a service account

1. Open **IAM & Admin → Service Accounts → Create service account**.
2. Give it a name, e.g. "btrack-groups". You don't need to grant it any IAM roles on the
   project — it needs no GCP permissions at all. Its authorization comes entirely from group
   membership (step 5).
3. Click **Done**.

## 4. Create a key

1. Open the service account you just created → **Keys** → **Add key** → **Create new key** →
   **JSON**. A `.json` file downloads to your machine. Treat it like a password.
2. Note the service account's email address, which looks like
   `btrack-groups@your-project.iam.gserviceaccount.com`. You'll add this to both groups in step 5.
3. The key goes to Cloudflare as an encrypted secret (step 6). Keep the downloaded file out of
   the git repo; once the secret is set you don't need it on disk.

## 5. Create the two Google Groups

1. Go to [groups.google.com](https://groups.google.com/) (as yourself, with your `@berkeley.edu`
   account — you don't need Workspace admin rights to create a group you own).

   Berkeley's Google Groups are addressed `@lists.berkeley.edu`, **not** `@berkeley.edu` — a
   different domain from the accounts signing in. That's expected: only the signing-in identity
   is restricted to `@berkeley.edu`, and the group addresses are never domain-checked. Use
   whatever address the group actually has.
2. **Create group** for the users list, e.g. `btrack-users@lists.berkeley.edu`. Add everyone who should
   be able to sign in as a **Member**.
3. **Create group** for the admins list, e.g. `btrack-admins@lists.berkeley.edu`. Add everyone who
   should get admin rights as a **Member**. (Admins should also be in the users group, or they
   won't pass the sign-in check — admin status doesn't imply sign-in access.)
4. For **each** of the two groups: open **Group settings → Members → Add members**, add the
   service account's email address (from step 4), and set its role to **Manager** or **Owner**
   (not plain "Member"). This is the step that actually grants the API access — without it,
   membership lookups return 403 even though the API is enabled and the credentials are valid.

Nested/child groups are **not** followed by this app (see the gotcha at the bottom) — members
must be added directly to these two groups, not to a subgroup of them.

## 6. Point the app at the groups

The two group addresses are ordinary config, so they live in `wrangler.jsonc`:

```jsonc
"vars": {
  "GOOGLE_USERS_GROUP": "btrack-users@lists.berkeley.edu",
  "GOOGLE_ADMINS_GROUP": "btrack-admins@lists.berkeley.edu"
}
```

The key is a secret, so it goes in encrypted — paste the whole JSON file when prompted:

```sh
npx wrangler secret put GOOGLE_SERVICE_ACCOUNT_JSON
```

On Workers the key **must** be inline JSON: there is no filesystem, so
`GOOGLE_SERVICE_ACCOUNT_FILE` only works when running locally under uvicorn, where either form
is accepted (inline JSON wins if both are set).

All three are required whenever `DEV_LOGIN` is not `1` — the app refuses to start without them
(see `Settings.validate()` in `src/app/config.py`). With `DEV_LOGIN=1`, local sign-in uses a
checkbox on the dev login form instead and never calls Google at all.

## How it works

At sign-in (after the existing `@berkeley.edu` / `hd` checks), the app calls the Cloud Identity
API once to check direct membership in the users group, and once for the admins group. The
result is cached in the signed session cookie, not re-checked on every page load — removing
someone from a group takes effect the next time they sign in, not immediately.

## Troubleshooting

- **403 from the Cloud Identity API** — almost always means the service account is not a
  Manager/Owner of the group being queried, or the Cloud Identity API isn't enabled on the
  project. Double-check step 2 and step 5.4.
- **404 on a group lookup** (`groups:lookup`) — the group email doesn't exist, or isn't visible to
  the service account. Check `GOOGLE_USERS_GROUP`/`GOOGLE_ADMINS_GROUP` for typos, and make sure
  you used the group's real domain (`@lists.berkeley.edu` at Berkeley), not `@berkeley.edu`.
- **404 on a membership check** (`memberships:lookup`) is *not* an error — it's the normal way the
  API says "this person is not a member," and the app treats it as such.
- **A user who should have access is rejected** — check they were added as a **direct** member of
  the group, not a member of a different group that's nested inside it. This app deliberately
  checks only direct membership (`memberships:lookup`), not transitive membership, so nested
  groups are not followed.
- **Why not use the transitive endpoints** (`checkTransitiveMembership`, `searchTransitiveGroups`,
  `getMembershipGraph`) **and support nested groups?** Those endpoints require a Google Workspace
  Enterprise Standard/Plus/Education or Cloud Identity Premium license and return 403 without one.
  Since there's no reliable way to tell in advance which license a given Workspace has, this app
  sticks to the direct, non-transitive membership check, which has no documented license
  requirement.
- **Sign-in fails with "temporarily unavailable"** — this means the Cloud Identity API call itself
  failed (bad/expired credentials, network error, 5xx from Google, etc.), and the app fails
  closed: it refuses to sign anyone in rather than guessing at group membership. Check the
  logs with `npx wrangler tail` for the underlying error.
- **Checking which secrets are set** — `npx wrangler secret list`. Values are never readable
  back, so to change a key just `put` it again.
