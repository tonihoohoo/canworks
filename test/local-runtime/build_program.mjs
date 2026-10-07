// Builds a Runtime v4 upload bundle from one ST file with the editor's
// compiler (STruC++, scripts/fetch-strucpp.sh), laid out as OpenPLC Editor's
// "Build only" writes it (compose-runtime-v4-bundle in the editor): the
// compiled TUs, generated.hpp, generated_debug.cpp, debug-map.json, the
// STruC++ runtime headers under strucpp_runtime/include, defines.h and an
// empty c_blocks.h. Enough for test/local-runtime/run.sh to run a real PLC
// program; projects with libraries or C blocks need the editor itself.
//
//   node build_program.mjs <strucpp command> <program.st> <bundle dir>
import { createHash } from "node:crypto";
import { copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { pathToFileURL } from "node:url";

const [cli, stFile, out] = process.argv.slice(2);
if (!cli || !stFile || !out) {
  console.error("usage: node build_program.mjs <strucpp command> <program.st> <bundle dir>");
  process.exit(2);
}
// The package of the command behind node_modules/.bin/strucpp.
let pkg = dirname(realpathSync(cli));
while (!existsSync(join(pkg, "package.json")) && dirname(pkg) !== pkg) pkg = dirname(pkg);
const { compile } = await import(pathToFileURL(join(pkg, "dist", "index.js")).href);

const source = readFileSync(stFile, "utf8");
const md5 = createHash("md5").update(source).digest("hex");
const r = compile(source, { debug: true, lineMapping: false, fileName: "program.st", md5 });
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
