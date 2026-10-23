// codec_run.js - lib/codec.js for test_nodered.py: reads {rows, image (hex),
// writes: [[name, value]]} on stdin, prints {values, image, errors}, so the
// Python side checks the bytes against images it packs itself.
"use strict";

const path = require("path");
const codec = require(path.join(__dirname, "..", "..", "canworks", "nodered_package", "lib", "codec"));

let text = "";
process.stdin.on("data", (d) => (text += d));
process.stdin.on("end", () => {
  const job = JSON.parse(text);
  const img = Buffer.from(job.image, "hex");
  const values = {};
  for (const r of job.rows) values[r.n] = codec.decode(img, r);
  const errors = {};
  const out = Buffer.from(img);
  for (const [name, value] of job.writes || []) {
    const err = codec.encode(out, job.rows.find((r) => r.n === name), value);
    if (err) errors[name] = err;
  }
  process.stdout.write(JSON.stringify({ values, image: out.toString("hex"), errors }));
});
