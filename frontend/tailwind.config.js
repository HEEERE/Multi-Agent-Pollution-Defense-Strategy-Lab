/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "Microsoft YaHei", "system-ui", "sans-serif"],
      },
      boxShadow: {
        signal: "0 0 0 1px rgba(20, 184, 166, 0.18), 0 14px 36px rgba(15, 23, 42, 0.12)",
      },
    },
  },
  plugins: [],
};
