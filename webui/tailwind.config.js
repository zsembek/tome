/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0f1216", panel: "#161b22", line: "#2a313c",
        fg: "#e6edf3", mut: "#8b949e", acc: "#4f9cf9",
      },
    },
  },
  plugins: [],
};
