# Stream Clips: Instagram Reels Publishing Setup Guide

This guide walks you through setting up Meta Graph API v22.0 to publish vertical Reels directly from the Stream Clips Dashboard.

Stream Clips uses **Meta System User Access Tokens (SUAT)** from your Meta Business Portfolio. This provides permanent or long-lived authentication without needing to re-login every hour.

---

## 1. Prerequisites & Account Requirements

To publish Instagram Reels via the Graph API, Meta requires:
1. **Instagram Professional Account**: Your account must be converted to an **Instagram Creator** or **Instagram Business** account (personal accounts cannot use the Graph API).
   - In Instagram mobile app: *Settings and privacy > Account type and tools > Switch to professional account*.
2. **Linked Facebook Page**: Your Instagram Professional account must be connected to a Facebook Page that you administer.
   - In Instagram mobile app: *Settings and privacy > Creator tools and controls > Connect or create a Facebook Page*.
3. **Meta Business Portfolio (formerly Business Manager)**: A verified Business Portfolio on [Meta Business Suite](https://business.facebook.com/).

---

## 2. Meta for Developers App Setup

1. Log in to [Meta for Developers](https://developers.facebook.com/).
2. Click **My Apps** > **Create App**.
3. Select **Other** as the use case, then click **Next**.
4. Select **Business** as the app type, then click **Next**.
5. Give your app a name (e.g. `StreamClips Uploader`), enter your email, and select your **Business Portfolio**.
6. Click **Create app**.

---

## 3. Configure Meta Business Portfolio & System User

Using a **System User** allows you to generate a long-lived Access Token that does not expire when your personal password changes.

1. Go to [Meta Business Settings](https://business.facebook.com/settings).
2. Select your Business Portfolio.
3. Under **Accounts**, navigate to:
   - **Pages**: Ensure your connected Facebook Page is listed.
   - **Instagram accounts**: Click **Add** and log in to attach your Instagram Professional account to this portfolio.
4. Under **Users**, click **System users**:
   - Click **Add**.
   - Set **System user name**: `StreamClips-Publisher`.
   - Set **System user role**: `Admin` (or `Employee`).
   - Click **Create system user**.

---

## 4. Assign Account Assets to the System User

1. In the **System users** table, select `StreamClips-Publisher`.
2. Click **Add Assets**.
3. Under **Pages**, select your connected Facebook Page and toggle **Full Control** (Manage Page).
4. Under **Instagram accounts**, select your Instagram account and toggle **Full Control** (Manage Instagram Account).
5. Click **Save Changes**.

---

## 5. Generate System User Access Token (SUAT)

1. While still selecting `StreamClips-Publisher`, click **Generate new token**.
2. Select the app you created in Step 2 (`StreamClips Uploader`).
3. Set **Token expiration**: Choose **Never** (or 60 days if required by your portfolio policy).
4. Select the **Required Permissions**:
   - `instagram_basic` (Read account details, username, profile photo)
   - `instagram_content_publish` (Create and publish Reels and feed posts)
   - `pages_show_list` (Discover linked Pages)
   - `pages_read_engagement` (Verify page status)
5. Click **Generate Token**.
6. **Copy the token immediately**: Meta displays this token only once.

> [!WARNING]
> Keep your token secure. Never commit it to GitHub, paste it into public forums, or share it. Stream Clips stores tokens in `~/.streamclips/auth/` outside the project repository.

---

## 6. Connect Account in Stream Clips Dashboard

1. Launch the Stream Clips Dashboard:
   ```powershell
   python scripts/dashboard.py
   ```
2. Open your browser at `http://127.0.0.1:5050`.
3. In the header bar, click **Instagram Settings** (the gear icon next to "Connect Instagram").
4. Paste your **System User Access Token**.
5. *(Optional)* If you run a custom static tunnel or reverse proxy, enter your **Public Tunnel URL** (e.g. `https://my-tunnel.example.com`). Leave blank to use automated Cloudflare Quick Tunnels.
6. Click **Save & Verify**.
7. The dashboard validates the token with Meta Graph API v22.0, fetches your Instagram `@username`, and displays a green indicator showing connected status.

---

## 7. How Reel Publishing Works

When you click **Publish to Instagram Reels** on any clip:
1. Stream Clips generates an unguessable 32-byte randomized path (e.g. `/video/<token>.mp4`).
2. An isolated, media-only HTTP server is launched on an ephemeral local port.
3. An automated Cloudflare Quick Tunnel (`cloudflared`) connects to this ephemeral port and obtains a public HTTPS URL (`https://<id>.trycloudflare.com`).
4. Stream Clips calls Meta's container creation API:
   `POST https://graph.facebook.com/v22.0/{ig-user-id}/media`
5. Meta's video crawler requests the video via HTTP HEAD and HTTP Range GET (`206 Partial Content`).
6. Stream Clips polls container status until it transitions to `FINISHED`.
7. Stream Clips calls Meta's publishing API:
   `POST https://graph.facebook.com/v22.0/{ig-user-id}/media_publish`
8. The ephemeral tunnel and media server are immediately terminated.
9. The published Reel link (`https://www.instagram.com/reel/<shortcode>/`) is saved to `clips.json` and displayed in the dashboard.

---

## 8. Common Errors & Troubleshooting

| Error Message | Cause | Resolution |
|---|---|---|
| `OAuthException (code 190): Invalid or expired access token` | The token has expired, was revoked, or contains typographical errors. | Generate a fresh System User token in Business Settings and reconnect. |
| `(#10) Application does not have permission for this action` | Missing `instagram_content_publish` permission on the token. | In Business Settings > System Users, generate a new token ensuring `instagram_content_publish` is checked. |
| `Could not detect an Instagram Professional or Creator account associated with this token` | The Instagram account is not assigned to the System User or is a personal account. | 1. Ensure Instagram account is set to Professional/Creator in app settings.<br/>2. In Meta Business Settings, go to *Instagram accounts*, add the account, and click *Add Assets* under your System User to assign it. |
| `Cloudflare Tunnel (cloudflared) is not installed` | `cloudflared` binary not found in system PATH. | Install via `winget install Cloudflare.cloudflared` and restart terminal, or configure a static tunnel URL in Instagram Settings. |
| `Timed out waiting for Meta to finish processing video` | Video file was unusually large, or network connection dropped during crawler ingestion. | Verify network stability and ensure video duration is within Instagram Reels limits (15 to 90 seconds). |
