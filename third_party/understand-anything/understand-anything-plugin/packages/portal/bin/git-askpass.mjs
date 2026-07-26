#!/usr/bin/env node

import fs from "node:fs";

const prompt = process.argv[2] || "";
if (/username/i.test(prompt)) {
  process.stdout.write(`${process.env.UA_GIT_USERNAME || "oauth2"}\n`);
} else {
  const tokenFile = process.env.UA_GIT_TOKEN_FILE;
  const token = tokenFile ? fs.readFileSync(tokenFile, "utf8").trim() : "";
  process.stdout.write(`${token}\n`);
}
