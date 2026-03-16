/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/templates/**/*.html",
    "./src/apps/**/templates/**/*.html"
  ],
  theme: {
    extend: {
      fontFamily: {
        display: ["Oswald", "ui-sans-serif", "system-ui", "sans-serif"],
        sans: ["Source Sans 3", "ui-sans-serif", "system-ui", "sans-serif"]
      },
      colors: {
        navy: {
          950: "#060B1A",
          900: "#0A1330",
          800: "#0F1B40",
          700: "#15265A"
        },
        patriot: {
          red: "#E11D48",
          blue: "#2563EB"
        }
      },
      boxShadow: {
        premium: "0 18px 50px rgba(0,0,0,.45)"
      }
    }
  },
  plugins: []
};
