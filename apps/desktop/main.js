const { app, BrowserWindow, shell } = require("electron");

// RESOLVE — native desktop shell. Personal use. Loads the live dashboard, so it
// auto-updates whenever you deploy (never needs a rebuild for features).
const APP_URL = "https://resolve-1-889i.onrender.com";

function createWindow() {
  const win = new BrowserWindow({
    width: 1320,
    height: 880,
    minWidth: 380,
    minHeight: 480,
    backgroundColor: "#07090e",
    titleBarStyle: "hiddenInset", // native macOS traffic lights over the dark UI
    webPreferences: { contextIsolation: true },
  });

  // Grant mic (voice / wake word); deny everything else.
  win.webContents.session.setPermissionRequestHandler((_wc, permission, cb) => {
    cb(permission === "media" || permission === "microphone");
  });

  win.loadURL(APP_URL);

  // tell the dashboard it's running inside the desktop shell, so artifact
  // file:// links reveal in Finder instead of copying the path
  win.webContents.on("dom-ready", () => {
    win.webContents.executeJavaScript("window.resolveDesktop = true;").catch(() => {});
  });

  const openLink = (url) => {
    if (url && url.startsWith("file://")) {
      // reveal the artifact in Finder rather than navigating the app to it
      shell.showItemInFolder(decodeURIComponent(url.replace(/^file:\/\//, "")));
    } else {
      shell.openExternal(url);
    }
  };

  // external links open in the real browser / Finder, not inside the app window
  win.webContents.setWindowOpenHandler(({ url }) => {
    openLink(url);
    return { action: "deny" };
  });
  // artifact local links render in-window (no target) → intercept the navigation
  win.webContents.on("will-navigate", (e, url) => {
    if (!url.startsWith(APP_URL)) {
      e.preventDefault();
      openLink(url);
    }
  });
}

app.whenReady().then(() => {
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
