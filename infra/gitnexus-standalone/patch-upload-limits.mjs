import fs from "node:fs";

const target = "/app/gitnexus/dist/server/upload-ingest.js";
let source = fs.readFileSync(target, "utf8");

const replacements = new Map([
  ["maxTotalBytes: 250 * 1024 * 1024,", "maxTotalBytes: Number.MAX_SAFE_INTEGER,"],
  ["maxFileBytes: 25 * 1024 * 1024,", "maxFileBytes: Number.MAX_SAFE_INTEGER,"],
  ["maxFiles: 20000,", "maxFiles: Number.MAX_SAFE_INTEGER,"],
  ["maxParts: 20100,", "maxParts: Number.MAX_SAFE_INTEGER,"],
  ["maxDirs: 50000,", "maxDirs: Number.MAX_SAFE_INTEGER,"],
  ["maxFieldBytes: 2 * 1024 * 1024,", "maxFieldBytes: Number.MAX_SAFE_INTEGER,"],
]);

for (const [before, after] of replacements) {
  const first = source.indexOf(before);
  if (first < 0 || source.indexOf(before, first + before.length) >= 0) {
    throw new Error(`expected exactly one GitNexus upload limit: ${before}`);
  }
  source = source.replace(before, after);
}

fs.writeFileSync(target, source);
