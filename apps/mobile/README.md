# RESOLVE — iOS app (Capacitor)

A native iOS shell around the hosted RESOLVE dashboard. **Personal / dev use only — not for the App Store.** It loads `https://resolve-1-889i.onrender.com`, so everything you already have keeps working: the login gate, the `/api` proxy, the control plane, voice/wake word, and finance. Change the web app + deploy to Render, and the app updates itself (it just loads the live URL) — no rebuild needed.

## Build it onto your iPhone (one time, on your Mac)

**Prereqs:** Xcode (from the App Store) · CocoaPods (`sudo gem install cocoapods`) · a free Apple ID.

```bash
cd apps/mobile
npm install
npx cap add ios        # generates the native ios/ project
npx cap sync           # installs pods + syncs the config
npx cap open ios       # opens the project in Xcode
```

**In Xcode:**
1. Select the **App** target → **Signing & Capabilities** → tick **Automatically manage signing** → choose your Apple ID as the Team.
2. Plug in your iPhone (unlocked, trusted), pick it as the run destination (top bar), press **▶**.
3. First launch: on the iPhone go to **Settings → General → VPN & Device Management → [your Apple ID] → Trust**. Re-open the app.

RESOLVE now lives on your home screen with its own icon.

> **Free Apple ID caveat:** apps signed with a *free* account expire after **7 days** — you'd re-run the build weekly. A paid Apple Developer account ($99/yr) makes it last a year and removes the hassle. Your call.

## Voice permission (needed for the wake word / voice)
After `npx cap add ios`, add these keys to `ios/App/App/Info.plist`:

```xml
<key>NSMicrophoneUsageDescription</key>
<string>RESOLVE uses the microphone for voice commands and the wake word.</string>
<key>NSSpeechRecognitionUsageDescription</key>
<string>RESOLVE uses speech recognition to understand voice commands.</string>
```

Then `npx cap sync` and rebuild.

## App icon
Drop a 1024×1024 RESOLVE icon into Xcode's **Assets.xcassets → AppIcon** (or use an icon set generator). Source art: `apps/dashboard/public/icon-192.png` / the `resolve-icon-dark` files.

## Config
See `capacitor.config.ts`. To point the app at a different dashboard URL, change `server.url` there and re-run `npx cap sync`.
