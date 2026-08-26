import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        obsidian: "#0D0D11",
        surface: "#15151D",
        card: "#1C1C26",
        line: "#2A2A38",
        sunrise: {
          DEFAULT: "#FF7A00",
          soft: "#FFA04D",
          dim: "#B35400",
        },
        ink: {
          DEFAULT: "#FFFFFF",
          sec: "#A0A0B2",
          mute: "#626275",
        },
      },
      borderRadius: { "2xl": "1rem", "3xl": "1.5rem" },
      boxShadow: {
        glow: "0 0 24px rgba(255,122,0,.35)",
        "glow-sm": "0 0 12px rgba(255,122,0,.28)",
        card: "0 10px 30px rgba(0,0,0,.45)",
      },
      fontFamily: {
        sans: ["Cairo", "Segoe UI", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};
export default config;
