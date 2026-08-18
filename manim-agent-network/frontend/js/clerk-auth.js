/* Clerk session auth for the studio SPA.
 *
 * Fetches the publishable key from the web tier (/auth-config.json), loads
 * clerk-js, gates the app on sign-in, and exposes:
 *   window.__authToken()  -> Promise<string|null>   (Bearer token for api())
 *   window.__authReady    -> Promise<void>           (resolves once auth settled)
 *
 * Graceful: if no publishable key is configured, auth is a no-op and the app
 * runs ungated (local/dev). NOTE: clerk-js v5 loading — verify the import URL
 * against current Clerk docs when wiring real keys.
 */
(function () {
  let _clerk = null;
  window.__authToken = async () => null; // default no-op until configured

  window.__authReady = (async () => {
    let cfg;
    try {
      cfg = await (await fetch("/auth-config.json")).json();
    } catch {
      return; // web tier not reachable / not configured -> ungated
    }
    const pk = cfg && cfg.clerk_publishable_key;
    if (!pk) return; // dev: no key -> ungated

    try {
      const mod = await import("https://cdn.jsdelivr.net/npm/@clerk/clerk-js@5/+esm");
      const Clerk = mod.Clerk || mod.default;
      _clerk = new Clerk(pk);
      await _clerk.load();

      if (!_clerk.user) {
        // not signed in -> Clerk hosted sign-in, returns here afterward
        await _clerk.redirectToSignIn({ redirectUrl: window.location.href });
        return; // navigation in progress
      }

      window.__authToken = async () => {
        try {
          return _clerk.session ? await _clerk.session.getToken() : null;
        } catch {
          return null;
        }
      };
      window.__clerk = _clerk; // for a sign-out button, etc.
    } catch (e) {
      console.error("clerk-auth: failed to initialise Clerk", e);
    }
  })();
})();
