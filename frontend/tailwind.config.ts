import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#030a11",
          900: "#06111b",
          850: "#091824",
          800: "#0c1d2a",
          700: "#143044",
        },
        cyan: {
          350: "#31c8ff",
          450: "#00aeea",
        },
      },
      boxShadow: {
        panel: "0 18px 60px rgba(0, 0, 0, 0.22)",
        glow: "0 0 24px rgba(0, 174, 234, 0.16)",
      },
      fontFamily: {
        sans: [
          "Inter",
          "\"Noto Sans SC\"",
          "\"Microsoft YaHei UI\"",
          "\"Microsoft YaHei\"",
          "sans-serif",
        ],
        mono: [
          "\"JetBrains Mono\"",
          "\"Cascadia Code\"",
          "\"SFMono-Regular\"",
          "Consolas",
          "monospace",
        ],
      },
    },
  },
  plugins: [],
} satisfies Config;
