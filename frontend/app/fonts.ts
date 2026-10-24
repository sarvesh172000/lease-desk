import { Inter, JetBrains_Mono } from "next/font/google";

/**
 * Self-hosted through next/font: no network request on load, and no layout
 * shift when the face swaps in, which matters on a screen full of figures.
 */
export const sans = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-sans",
  axes: ["opsz"],
});

export const mono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-mono",
  weight: ["400", "500"],
});
