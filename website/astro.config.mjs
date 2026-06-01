// @ts-check
import { defineConfig } from "astro/config";
import tailwindcss from "@tailwindcss/vite";

// Sitio de proyecto en GitHub Pages: https://jonimartin27.github.io/inferbench/
// Si más adelante usas un dominio propio, pon `site` a ese dominio y `base` a "/".
export default defineConfig({
  site: "https://jonimartin27.github.io",
  base: "/inferbench",
  vite: {
    plugins: [tailwindcss()],
  },
});
