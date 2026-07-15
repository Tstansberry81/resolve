// electron-builder afterPack hook: ad-hoc sign the packed .app.
//
// The build skips real signing (identity: null — no Apple Developer cert), but
// a fully unsigned bundle signs as Identifier=Electron, so macOS TCC can't
// hold a microphone grant for it and the mic "blinks" (permission retry loop).
// Ad-hoc signing stamps the real bundle id (com.tstansberry.resolve) so the
// grant sticks — this is the proven manual fix, applied automatically so every
// fresh .dmg works out of the box.
const { execFileSync } = require("child_process");
const path = require("path");

exports.default = async function adhocSign(context) {
  if (context.electronPlatformName !== "darwin") return;
  const appName = context.packager.appInfo.productFilename;
  const appPath = path.join(context.appOutDir, `${appName}.app`);
  execFileSync("codesign", ["--force", "--deep", "--sign", "-", appPath], { stdio: "inherit" });
  execFileSync("codesign", ["--verify", appPath], { stdio: "inherit" });
  console.log(`  • ad-hoc signed ${appName}.app (mic permission survives installs)`);
};
