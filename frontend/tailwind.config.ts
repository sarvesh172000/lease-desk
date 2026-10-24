import type { Config } from "tailwindcss";

/**
 * A restrained ledger palette: warm paper, ink, one deep-teal accent, and four
 * status hues that are distinguishable on a washed-out projector.
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#f6f5f1",
        surface: "#ffffff",
        sunken: "#efede7",
        line: "#dedbd2",
        "line-strong": "#c7c3b8",
        ink: { DEFAULT: "#1b1f24", soft: "#454b53", muted: "#6b7079", faint: "#9196a0" },
        accent: { DEFAULT: "#0f5c5a", soft: "#e3efee", strong: "#0a4442" },
        ok: { DEFAULT: "#1d6b3d", soft: "#e4f1e8", line: "#a9d2b7" },
        bad: { DEFAULT: "#a8261f", soft: "#fbe9e7", line: "#eab1ab" },
        warn: { DEFAULT: "#8a5a00", soft: "#fbf0d9", line: "#e6c886" },
        esc: { DEFAULT: "#5b3a9a", soft: "#efe9f9", line: "#c9b8ea" },
        mark: "#e0a800",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "Helvetica Neue", "Arial", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "Liberation Mono", "monospace"],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      },
      boxShadow: {
        card: "0 1px 0 rgba(27,31,36,0.04), 0 1px 2px rgba(27,31,36,0.06)",
      },
    },
  },
  plugins: [],
};

export default config;
