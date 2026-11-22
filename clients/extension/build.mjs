// Builds the MV3 extension into dist/ and a shareable zip.
// Extension pages + background are ES modules; each content script is a self-contained IIFE
// (content scripts cannot be modules).
import { copyFileSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { crc32, deflateRawSync } from "node:zlib";
import { build } from "vite";

const root = dirname(fileURLToPath(import.meta.url));
const src = resolve(root, "src");
const dist = resolve(root, "dist");
rmSync(dist, { recursive: true, force: true });

const common = { configFile: false, logLevel: "warn", publicDir: false };

// 1. Extension pages (popup, options, full result page).
await build({
  ...common,
  root: src,
  base: "./",
  build: {
    outDir: dist,
    emptyOutDir: false,
    target: "chrome120",
    modulePreload: false,
    rollupOptions: {
      input: {
        popup: resolve(src, "popup/popup.html"),
        options: resolve(src, "options/options.html"),
        result: resolve(src, "result/result.html"),
      },
      output: { entryFileNames: "assets/[name].js", chunkFileNames: "assets/[name]-[hash].js", assetFileNames: "assets/[name][extname]" },
    },
  },
});

// 2. Background service worker (ES module) and content scripts (IIFE), one bundle each.
const bundles = [
  { entry: "background.ts", name: "background", format: "es" },
  { entry: "content/search.ts", name: "content-search", format: "iife" },
  { entry: "content/maps.ts", name: "content-maps", format: "iife" },
  { entry: "content/banner.ts", name: "content-banner", format: "iife" },
];
for (const b of bundles) {
  await build({
    ...common,
    root,
    build: {
      outDir: dist,
      emptyOutDir: false,
      target: "chrome120",
      minify: true,
      lib: { entry: resolve(src, b.entry), formats: [b.format], name: b.name.replace(/-/g, "_"), fileName: () => `${b.name}.js` },
    },
  });
}

// 3. Manifest + icons.
copyFileSync(resolve(src, "manifest.json"), resolve(dist, "manifest.json"));
mkdirSync(resolve(dist, "icons"), { recursive: true });
for (const f of readdirSync(resolve(root, "icons"))) copyFileSync(resolve(root, "icons", f), resolve(dist, "icons", f));

// 4. Zip for sharing (stored + deflate, no external tools).
function walk(dir) {
  return readdirSync(dir).flatMap((n) => (statSync(join(dir, n)).isDirectory() ? walk(join(dir, n)) : [join(dir, n)]));
}
const files = walk(dist);
const chunks = [];
const central = [];
let offset = 0;
for (const file of files) {
  const name = Buffer.from(relative(dist, file).split("\\").join("/"));
  const data = readFileSync(file);
  const comp = deflateRawSync(data);
  const crc = crc32(data) >>> 0;
  const local = Buffer.alloc(30);
  local.writeUInt32LE(0x04034b50, 0); local.writeUInt16LE(20, 4); local.writeUInt16LE(0, 6); local.writeUInt16LE(8, 8);
  local.writeUInt32LE(0, 10); local.writeUInt32LE(crc, 14); local.writeUInt32LE(comp.length, 18);
  local.writeUInt32LE(data.length, 22); local.writeUInt16LE(name.length, 26); local.writeUInt16LE(0, 28);
  chunks.push(local, name, comp);
  const cen = Buffer.alloc(46);
  cen.writeUInt32LE(0x02014b50, 0); cen.writeUInt16LE(20, 4); cen.writeUInt16LE(20, 6); cen.writeUInt16LE(0, 8);
  cen.writeUInt16LE(8, 10); cen.writeUInt32LE(0, 12); cen.writeUInt32LE(crc, 16); cen.writeUInt32LE(comp.length, 20);
  cen.writeUInt32LE(data.length, 24); cen.writeUInt16LE(name.length, 28); cen.writeUInt32LE(0, 30); cen.writeUInt32LE(0, 34);
  cen.writeUInt32LE(0, 38); cen.writeUInt32LE(offset, 42);
  central.push(cen, name);
  offset += 30 + name.length + comp.length;
}
const cenSize = central.reduce((n, b) => n + b.length, 0);
const end = Buffer.alloc(22);
end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(files.length, 8); end.writeUInt16LE(files.length, 10);
end.writeUInt32LE(cenSize, 12); end.writeUInt32LE(offset, 16);
writeFileSync(resolve(root, "hami-extension.zip"), Buffer.concat([...chunks, ...central, end]));
console.warn(`built ${files.length} files -> ${relative(process.cwd(), dist)} and hami-extension.zip`);
