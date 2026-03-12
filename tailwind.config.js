/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/templates/**/*.html",
    "./src/apps/**/templates/**/*.html"
  ],
  theme: {
    extend: {
      fontFamily: {
        display: ["Cinzel", "ui-serif", "Georgia", "serif"],
        sans: ["DM Sans", "ui-sans-serif", "system-ui", "sans-serif"]
      },
      colors: {
        ink: {
          950: "#07070B",
          900: "#0B0C12",
          800: "#101221"
        },
        patriot: {
          red: "#E11D48",
          blue: "#2563EB",
          gold: "#D6B25E"
        }
      },
      boxShadow: {
        premium: "0 18px 50px rgba(0,0,0,.45)"
      }
    }
  },
  plugins: []
};
