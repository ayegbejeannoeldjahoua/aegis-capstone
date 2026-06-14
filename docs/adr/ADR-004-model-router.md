# ADR-004 Model router

Decision: model refs use `provider/model`. The registry controls allowlists, aliases, primary/fallbacks, provider auth, region, risk tier, and local/hosted classification.

User-pinned unknown models fail visibly. Auto fallbacks are allowed only from configured fallback chains.
