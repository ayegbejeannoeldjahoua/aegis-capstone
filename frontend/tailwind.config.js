/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx,ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Align Tailwind's defaults with the Aegis dark-slate palette
        // so ported pages still feel native to the theme.
      },
    },
  },
  plugins: [],
}
