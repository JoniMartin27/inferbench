// @ts-check
import { defineConfig } from "astro/config";
import tailwindcss from "@tailwindcss/vite";

// Sitio de proyecto en GitHub Pages: https://jonimartin27.github.io/inferbench/
// Si más adelante usas un dominio propio, pon `site` a ese dominio y `base` a "/".
//
// Tailwind entra por el plugin de Vite, no por PostCSS: desde astro 7 (rolldown-vite) el
// `@import "tailwindcss"` de global.css se resolvía como ruta relativa y el build moría con
// `ENOENT ... /website/tailwindcss`. MEDIDO: con `@tailwindcss/postcss` astro 7 no compila.
export default defineConfig({
  site: "https://jonimartin27.github.io",
  base: "/inferbench",
  vite: { plugins: [tailwindcss()] },
});
