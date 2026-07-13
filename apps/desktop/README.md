# RESOLVE — desktop app (Electron)

A native macOS app around the hosted RESOLVE dashboard. **Personal use.** It loads
the live site, so it **auto-updates whenever you deploy** — you never rebuild for
features. Same backend/data as the web + PWA + iOS.

## Install
1. Open `dist/RESOLVE-<version>-arm64.dmg`.
2. Drag **RESOLVE** into **Applications**.
3. First launch (unsigned personal build): **right-click the app → Open → Open**
   to get past Gatekeeper. After that it opens normally.

## Rebuild (only if you change the native shell — window size, icon, URL)
```bash
cd apps/desktop
npm install
npm run dist        # -> dist/RESOLVE-<version>-arm64.dmg  (unsigned, personal)
```
Change the target URL in `main.js` (`APP_URL`). Mic permission is declared in
`package.json` build.mac.extendInfo.

Note: built for Apple Silicon (arm64). For an Intel Mac, add `"x64"` to the mac
target and rebuild.
