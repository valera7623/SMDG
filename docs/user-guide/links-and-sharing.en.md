# Links and file sharing

SMDG lets you share files via **time-limited secure links** without giving the recipient your password.

## Create a link

1. In the file list click **Create link**.
2. Set options (if available):
   - expiry (TTL);
   - maximum download count.
3. Copy the generated URL.

## One-shot links

By default a link may be **one-shot** — after the first download it becomes invalid.

!!! tip "Security"
    One-shot links reduce leak risk: even if the URL appears in proxy logs, it cannot be reused.

## Share with recipient

Send the link over a secure channel (E2E messenger, corporate email). Do not post links in public chats.

The recipient:

1. Opens the link in a browser.
2. Downloads the decrypted file (no login required for public links).

## Revoke a link

An administrator or file owner can revoke a link early via the admin panel or API.

## Audit

All link operations are logged:

- link creation;
- download via link;
- expiry / revocation.

Audit export: [API — admin](../api/admin.md).

## Webhooks

A `file.downloaded` event may be sent to a configured endpoint on link download.

See [Webhooks](../api/webhooks.md).
