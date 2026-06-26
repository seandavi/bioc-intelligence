/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Subtle Bioconductor-adjacent accent.
        bioc: {
          50: "#eef6fb",
          100: "#d6e9f5",
          500: "#1f7bbf",
          600: "#1a6aa6",
          700: "#155688",
        },
      },
    },
  },
  plugins: [],
};
