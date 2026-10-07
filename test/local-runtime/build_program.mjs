// Builds a Runtime v4 upload bundle from one ST file with the editor's
// compiler (STruC++, scripts/fetch-strucpp.sh), laid out as OpenPLC Editor's
// "Build only" writes it (compose-runtime-v4-bundle in the editor): the
// compiled TUs, generated.hpp, generated_debug.cpp, debug-map.json, the
// STruC++ runtime headers under strucpp_runtime/include, defines.h and an
// empty c_blocks.h. Enough for test/local-runtime/run.sh to run a real PLC
// program. `--lib DIR` adds the ST libraries in DIR (*.stlib) and the
// compiler's bundled ones (PLCopen SoftMotion), as the editor does for a
// project with libraries; C/C++ blocks (the SDO blocks) need the editor's
// own glue and are not supported.
//
//   node build_program.mjs <strucpp command> <program.st> <bundle dir> [--lib DIR]...
import { createHash } from "node:crypto";
import { copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { pathToFileURL } from "node:url";

const [cli, stFile, out, ...rest] = process.argv.slice(2);
const libDirs = [];
for (let i = 0; i < rest.length; i += 2) {
  if (rest[i] !== "--lib" || !rest[i + 1]) {
    console.error(`unknown option: ${rest[i]}`);
    process.exit(2);
  }
  libDirs.push(rest[i + 1]);
}
if (!cli || !stFile || !out) {
  console.error("usage: node build_program.mjs <strucpp command> <program.st> <bundle dir> [--lib DIR]...");
  process.exit(2);
}
// The package of the command behind node_modules/.bin/strucpp.
let pkg = dirname(realpathSync(cli));
while (!existsSync(join(pkg, "package.json")) && dirname(pkg) !== pkg) pkg = dirname(pkg);
const { compile } = await import(pathToFileURL(join(pkg, "dist", "index.js")).href);
let libraries;
if (libDirs.length) {
  const { discoverStlibs } = await import(pathToFileURL(join(pkg, "dist", "node", "index.js")).href);
  libraries = [join(pkg, "libs"), ...libDirs].flatMap((d) => discoverStlibs(d));
}

const source = readFileSync(stFile, "utf8");
const md5 = createHash("md5").update(source).digest("hex");
const r = compile(source, { debug: true, lineMapping: false, fileName: "program.st", md5, ...(libraries ? { libraries } : {}) });
if (!r.success) {
  for (const e of r.errors) console.error(`program.st:${e.line}: ${e.message}`);
  process.exit(1);
}
mkdirSync(join(out, "strucpp_runtime", "include"), { recursive: true });
writeFileSync(join(out, "program.st"), source);
writeFileSync(join(out, "generated.hpp"), r.headerCode);
for (const f of r.cppFiles && r.cppFiles.length ? r.cppFiles : [{ name: "generated.cpp", content: r.cppCode }])
  writeFileSync(join(out, f.name), f.content);
writeFileSync(join(out, "generated_debug.cpp"), r.debugTableCpp || "");
writeFileSync(join(out, "debug-map.json"), JSON.stringify(r.debugMap || {}, null, 2));
writeFileSync(join(out, "defines.h"), `#pragma once\n// Program MD5\n#define PROGRAM_MD5 "${md5}"\n`);
writeFileSync(join(out, "c_blocks.h"), "// Empty file\n");
const inc = join(pkg, "src", "runtime", "include");
for (const name of readdirSync(inc)) copyFileSync(join(inc, name), join(out, "strucpp_runtime", "include", name));
console.log(`bundle written to ${out} (md5 ${md5})`);
