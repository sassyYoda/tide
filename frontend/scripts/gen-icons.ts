#!/usr/bin/env tsx
/**
 * Generate placeholder PWA icons in marine-pragmatic palette.
 *
 *   icon-192.png            (Android manifest minimum)
 *   icon-512.png            (Android splash + larger)
 *   icon-maskable-512.png   (Android adaptive icon w/ 10% safe zone padding)
 *   apple-touch-icon-180.png (iOS Add-to-Home-Screen — P9 pitfall guard)
 *   favicon.ico             (browser tab)
 *
 * MVP placeholders: solid teal-700 (#0F766E) square with a sand-colored "T".
 * Designed icons can replace these later without code changes.
 */
import sharp from "sharp"
// @ts-expect-error to-ico has no published types (small CJS module)
import toIco from "to-ico"
import { readFileSync, writeFileSync, unlinkSync, mkdirSync } from "node:fs"
import { resolve, dirname } from "node:path"
import { fileURLToPath } from "node:url"

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)
const ROOT = resolve(__dirname, "..")

interface Spec {
  out: string
  size: number
  maskable: boolean
}

const specs: Spec[] = [
  { out: "public/icons/icon-192.png", size: 192, maskable: false },
  { out: "public/icons/icon-512.png", size: 512, maskable: false },
  { out: "public/icons/icon-maskable-512.png", size: 512, maskable: true },
  { out: "public/icons/apple-touch-icon-180.png", size: 180, maskable: false },
]

function svgFor(size: number, maskable: boolean): string {
  // Maskable: pad 10% so the safe zone (the inner 80%) holds the glyph;
  // Android may crop up to 10% on each edge for adaptive icons.
  const padding = maskable ? Math.round(size * 0.1) : 0
  const inner = size - 2 * padding
  const fontSize = Math.round(inner * 0.6)
  return `
    <svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}">
      <rect width="${size}" height="${size}" fill="#0F766E"/>
      <text x="50%" y="50%" font-family="serif" font-size="${fontSize}" font-weight="bold"
            fill="#FAF8F1" text-anchor="middle" dominant-baseline="central">T</text>
    </svg>`
}

async function main(): Promise<void> {
  mkdirSync(resolve(ROOT, "public/icons"), { recursive: true })
  for (const s of specs) {
    const outPath = resolve(ROOT, s.out)
    const buf = Buffer.from(svgFor(s.size, s.maskable))
    await sharp(buf).png().toFile(outPath)
    console.log(`wrote ${s.out} (${s.size}x${s.size}${s.maskable ? " maskable" : ""})`)
  }

  // favicon.ico — render a 32x32 PNG, convert to ICO, then drop the temp PNG.
  const tmpFavicon = resolve(ROOT, "public/icons/_favicon-32.png")
  await sharp(Buffer.from(svgFor(32, false))).png().toFile(tmpFavicon)
  const ico = await toIco([readFileSync(tmpFavicon)])
  writeFileSync(resolve(ROOT, "public/icons/favicon.ico"), ico)
  unlinkSync(tmpFavicon)
  console.log("wrote public/icons/favicon.ico (32x32)")
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
