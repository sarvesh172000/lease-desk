import type { Config } from "tailwindcss";
import animate from "tailwindcss-animate";

/**
 * Every colour is a CSS variable, so switching theme is one attribute on
 * <html> rather than a second set of classes on every element. A hex in a
 * .tsx file breaks that, which is why there are none.
 */
const rgb = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

const config: Config = {
  darkMode: ["class", '[data-theme="dark"]'],
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: rgb("bg"),
        surface: rgb("surface"),
        raised: rgb("raised"),
        sunken: rgb("sunken"),
        line: { DEFAULT: rgb("line"), strong: rgb("line-strong") },
        ink: {
          DEFAULT: rgb("ink"),
          soft: rgb("ink-soft"),
          muted: rgb("ink-muted"),
          faint: rgb("ink-faint"),
        },
        accent: {
          DEFAULT: rgb("accent"),
          soft: rgb("accent-soft"),
          strong: rgb("accent-strong"),
          ink: rgb("accent-ink"),
        },
        ok: { DEFAULT: rgb("ok"), soft: rgb("ok-soft"), line: rgb("ok-line") },
        bad: { DEFAULT: rgb("bad"), soft: rgb("bad-soft"), line: rgb("bad-line") },
        warn: { DEFAULT: rgb("warn"), soft: rgb("warn-soft"), line: rgb("warn-line") },
        esc: { DEFAULT: rgb("esc"), soft: rgb("esc-soft"), line: rgb("esc-line") },
        // Kept so existing screens keep rendering while they are migrated.
        paper: rgb("bg"),
        mark: rgb("warn"),
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
        "display": ["clamp(2.75rem, 7vw, 5.5rem)", { lineHeight: "0.95", letterSpacing: "-0.035em" }],
        "headline": ["clamp(1.75rem, 3.4vw, 2.75rem)", { lineHeight: "1.1", letterSpacing: "-0.02em" }],
      },
      borderRadius: { xs: "6px", sm: "10px", DEFAULT: "10px", md: "14px", lg: "20px", xl: "28px" },
      boxShadow: {
        // Three levels. Flat, raised, floating. Nothing else.
        raised: "0 1px 0 rgb(var(--shadow) / 0.04), 0 2px 8px -2px rgb(var(--shadow) / 0.12)",
        float: "0 8px 30px -6px rgb(var(--shadow) / 0.28), 0 2px 8px -2px rgb(var(--shadow) / 0.16)",
        glow: "0 0 0 1px rgb(var(--accent) / 0.25), 0 0 24px -4px rgb(var(--accent) / 0.35)",
      },
      transitionTimingFunction: { out: "cubic-bezier(.2,.8,.2,1)" },
      transitionDuration: { fast: "120ms", base: "200ms", slow: "420ms" },
      keyframes: {
        "fade-up": { from: { opacity: "0", transform: "translateY(8px)" }, to: { opacity: "1", transform: "none" } },
        "draw": { from: { strokeDashoffset: "1" }, to: { strokeDashoffset: "0" } },
        "pulse-dot": { "0%,100%": { opacity: "1" }, "50%": { opacity: "0.35" } },
        "drift": { "0%,100%": { transform: "translate3d(0,0,0) scale(1)" }, "50%": { transform: "translate3d(2%,-2%,0) scale(1.06)" } },
      },
      animation: {
        "fade-up": "fade-up 420ms cubic-bezier(.2,.8,.2,1) both",
        "pulse-dot": "pulse-dot 2s ease-in-out infinite",
        "drift": "drift 24s ease-in-out infinite",
      },
    },
  },
  plugins: [animate],
};

export default config;
