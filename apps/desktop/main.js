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

  // external links open in the real browser, not inside the app window
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
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
