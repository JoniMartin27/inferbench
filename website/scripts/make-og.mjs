import sharp from "sharp";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const svg = readFileSync(join(__dirname, "og-source.svg"));
const out = join(__dirname, "..", "public", "og.png");

await sharp(svg, { density: 144 })
  .resize(1200, 630)
  .png({ quality: 90 })
  .toFile(out);

console.log("og.png escrito en", out);
