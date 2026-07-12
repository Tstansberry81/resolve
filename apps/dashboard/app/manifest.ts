import type { MetadataRoute } from "next";

// Makes the dashboard installable as a standalone app on Mac/Windows/mobile
// (Chrome/Edge "Install app", Safari "Add to Dock" / "Add to Home Screen").
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "RESOLVE",
    short_name: "RESOLVE",
    description: "Trav's autonomous agent command center",
    start_url: "/",
    display: "standalone",
    background_color: "#07090e",
    theme_color: "#07090e",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
    ],
  };
}
