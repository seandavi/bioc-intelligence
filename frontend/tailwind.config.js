import defaults from "tailwindcss/colors";

// Bioconductor brand palette, steps copied from https://bioconductor.org/style/base/colors.css
// (key 300 is the unsuffixed base, e.g. --primary). See docs/branding.md.
// `theme.colors` (not `extend`) so only brand colours exist; Tailwind red stays for errors.
/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    colors: {
      transparent: "transparent",
      current: "currentColor",
      white: "#ffffff",
      red: defaults.red,
      ink: "#070707", // --default-body
      primary: {
        50: "#ebf4f7",
        75: "#add2dd",
        100: "#8bc0cf",
        200: "#59a5bb",
        300: "#3792ad",
        400: "#035771",
        500: "#003242",
      },
      secondary: {
        50: "#f3fae9",
        75: "#cfe9a6",
        100: "#bbe081",
        200: "#9ed34a",
        300: "#8aca25",
        400: "#618d1a",
        500: "#547b17",
        // Chip text from the scheme-B mockup; not in colors.css (5.70:1 on s75).
        600: "#3f5d10",
      },
      warning: {
        50: "#fef9eb",
        300: "#f1c736",
        400: "#a98b26",
        500: "#937921",
      },
      neutral: {
        50: "#f9f9f9",
        75: "#e7e8ea",
        100: "#a1a6b3",
        200: "#797f92",
        300: "#5d657c",
        400: "#414757",
        500: "#393e4c",
      },
      // --gradient-brand end stops.
      brand: { teal: "#0087af", green: "#18a603" },
      // Semantic metric colours (src/index.css): text shade for values, fill for bars/borders.
      metric: {
        pubs: "var(--metric-pubs)",
        "pubs-fill": "var(--metric-pubs-fill)",
        usage: "var(--metric-usage)",
        "usage-fill": "var(--metric-usage-fill)",
        grants: "var(--metric-grants)",
        "grants-fill": "var(--metric-grants-fill)",
        people: "var(--metric-people)",
        "people-fill": "var(--metric-people-fill)",
      },
    },
  },
  plugins: [],
};
