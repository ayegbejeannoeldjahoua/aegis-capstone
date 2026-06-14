# Channels and real-time use

The production-mode package implements HTTP and WebSocket channels directly. The channel registry defines adapter seams for Slack, Microsoft Teams, Discord, Telegram, WhatsApp, and others.

Extracted design patterns included here:

- channel adapters should never be the root of trust;
- unknown direct-message senders are rejected or paired;
- group activation requires mention by default;
- inbound content is untrusted;
- channel identity must map to OIDC subject or an approved pairing record;
- every action is rechecked against the PDP with the original requester context.

Production channel adapters should call the same `/v1/ask` command-plane path or an internal equivalent after OIDC/pairing resolution.
