# InferBench — Web (landing)

Landing page de [InferBench](../README.md). Astro + Tailwind v4, estática, desplegada en GitHub Pages.

🔗 **En vivo:** https://jonimartin27.github.io/inferbench/

## Desarrollo

```bash
cd website
npm install
npm run dev        # http://localhost:4321/inferbench/
```

Otros scripts:

```bash
npm run build      # genera dist/ (estático)
npm run preview    # sirve dist/ localmente
```

## Despliegue

Automático vía GitHub Actions ([.github/workflows/deploy-website.yml](../.github/workflows/deploy-website.yml)):
cada push a `master` que toque `website/**` reconstruye y publica en GitHub Pages.

> Requiere que en **Settings → Pages → Source** del repo esté seleccionado **GitHub Actions** (paso único, ya hecho).

## Imagen Open Graph

La preview social (`public/og.png`, 1200×630) se genera desde un SVG, de forma reproducible:

```bash
node scripts/make-og.mjs     # lee scripts/og-source.svg → public/og.png (usa sharp)
```

Para cambiar textos/métricas edita [`scripts/og-source.svg`](scripts/og-source.svg) y vuelve a ejecutar el script.
(`sharp` se instala on-demand; si falta: `npm install --no-save sharp`.)

## Dominio propio (opcional)

Para usar un dominio en vez de la ruta `/inferbench/`:

1. En [`astro.config.mjs`](astro.config.mjs) pon `site: "https://tu-dominio"` y `base: "/"`.
2. Actualiza las URLs absolutas en `public/robots.txt` y `public/sitemap.xml`.
3. Añade un `public/CNAME` con el dominio y configúralo en Settings → Pages.

## Estructura

```
website/
├── astro.config.mjs        # site + base "/inferbench" + Tailwind
├── src/
│   ├── layouts/Layout.astro # <head>, SEO/OG, scroll-reveal
│   ├── pages/index.astro    # la landing completa + demo animada
│   └── styles/global.css    # tema (paleta de la app) + animaciones
├── public/                  # favicon.svg, og.png, robots.txt, sitemap.xml
└── scripts/                 # og-source.svg + make-og.mjs (generador del OG)
```
