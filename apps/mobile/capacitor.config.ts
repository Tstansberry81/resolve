import type { CapacitorConfig } from "@capacitor/cli";

// RESOLVE — native iOS shell (Capacitor). Personal / dev use only, NOT for the
// App Store. It loads the live dashboard so SSR, the password gate, the /api
// proxy, the control plane, voice, and finance all keep working unchanged.
// Change the web app + deploy to Render, and the app picks it up automatically.
const config: CapacitorConfig = {
  appId: "com.tstansberry.resolve",
  appName: "RESOLVE",
  webDir: "www",
  server: {
    url: "https://resolve-1-889i.onrender.com",
    cleartext: false,
  },
  ios: {
    contentInset: "always",
    backgroundColor: "#07090e",
    // allow the mic/getUserMedia inside the WKWebView (voice/wake word)
    limitsNavigationsToAppBoundDomains: false,
  },
};

export default config;
