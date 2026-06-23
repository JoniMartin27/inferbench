/** @type {import('tailwindcss').Config} */
// Tema Fervon (forja) — carbon + ember. Remapeamos las escalas de color de Tailwind
// usadas por la UI (slate/indigo/emerald/amber/rose/purple/cyan) a la paleta de la marca
// para reskinear todas las utilidades existentes sin tocar cada clase en los JSX.
//
// Mapeo canónico:
//   carbon #0E0B0A · panel #16110E · panel-2 #1A1310 · border #2C211B
//   bone #EFE7DC (texto) · ash #A89A8E (texto dim)
//   ember #FF6A00 (acento) · brasa #E0480F (acento oscuro/hover) · ember-dim #7A3A16
//   ambar #FFB02E (acento 2) · gold #FFD76A · danger #FF6B6B · verde permitido #8FD06B
//   texto sobre acento #2A1402

// Escala neutra "carbon" cálida (sustituye slate frío).
const carbon = {
  50: "#EFE7DC", // bone
  100: "#E3DACE",
  200: "#CDBFB0",
  300: "#B0A296", // ash claro
  400: "#A89A8E", // ash
  500: "#8A7C70",
  600: "#5C4E44",
  700: "#2C211B", // border / line
  800: "#241A15",
  900: "#1A1310", // panel-2 / card
  950: "#0E0B0A", // carbon / bg
};

// Acento primario ember (sustituye indigo/azul/cyan/teal de acento).
const ember = {
  50: "#FFE9D6",
  100: "#FFD3AD",
  200: "#FFB785",
  300: "#FFB86B", // link cálido
  400: "#FF8A3C",
  500: "#FF6A00", // ember
  600: "#E0480F", // brasa
  700: "#B83C0D",
  800: "#7A3A16", // ember-dim
  900: "#5A2A10",
  950: "#2A1402", // texto sobre acento
};

// Acento secundario ámbar/oro (sustituye amber frío / verde categórico secundario).
const ambar = {
  50: "#FFF3D6",
  100: "#FFE7AD",
  200: "#FFD76A", // gold
  300: "#FFC74A",
  400: "#FFB02E", // ámbar
  500: "#F59E1B",
  600: "#D9870F",
  700: "#A8690C",
  800: "#7A4D0A",
  900: "#5A3908",
  950: "#2A1A04",
};

// Verde permitido (éxito semántico) — se mantiene, no es acento frío.
const verde = {
  50: "#EAF7DE",
  100: "#D6EFC1",
  200: "#BBE49C",
  300: "#A3DA82",
  400: "#8FD06B", // verde permitido
  500: "#74B84F",
  600: "#5A9A3A",
  700: "#46772E",
  800: "#345722",
  900: "#243C18",
  950: "#142309",
};

// Danger (error real) — se mantiene cálido-rojo, NO es acento.
const danger = {
  50: "#FFE5E5",
  100: "#FFC9C9",
  200: "#FFA8A8",
  300: "#FF8F8F",
  400: "#FF6B6B", // danger
  500: "#F25555",
  600: "#D63F3F",
  700: "#A83030",
  800: "#7A2424",
  900: "#561A1A",
  950: "#2A0C0C",
};

export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        accent: {
          DEFAULT: "#FF6A00", // ember
        },
        // Neutros cálidos.
        slate: carbon,
        gray: carbon,
        neutral: carbon,
        zinc: carbon,
        // Acento frío → ember.
        indigo: ember,
        purple: ember,
        violet: ember,
        blue: ember,
        cyan: ember,
        sky: ember,
        teal: ember,
        orange: ember,
        fuchsia: ember,
        pink: ember,
        // Secundario → ámbar/oro.
        amber: ambar,
        yellow: ambar,
        // Éxito semántico permitido.
        emerald: verde,
        green: verde,
        // Error real.
        rose: danger,
        red: danger,
      },
    },
  },
  plugins: [],
};
