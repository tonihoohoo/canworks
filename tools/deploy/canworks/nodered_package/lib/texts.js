// texts.js - words for ERROR_IDs, SDO abort codes and control results.
"use strict";

const L = require("./layout");

// family: "sdo", "can" or "j1939"
function errorText(family, id) {
  const t = (L.errorTexts[family] || {})[String(id)] || L.errorTexts.all[String(id)];
  return t || "ERROR_ID " + id;
}

const ABORTS = {
  0x05030000: "toggle bit not alternated",
  0x05040000: "SDO protocol timed out",
  0x05040001: "command specifier not valid or unknown",
  0x06010000: "unsupported access to an object",
  0x06010001: "attempt to read a write-only object",
  0x06010002: "attempt to write a read-only object",
  0x06020000: "object does not exist",
  0x06040041: "object cannot be mapped to the PDO",
  0x06040042: "the number and length of the objects to be mapped would exceed the PDO length",
  0x06040043: "general parameter incompatibility",
  0x06060000: "access failed due to a hardware error",
  0x06070010: "data type does not match, length of service parameter does not match",
  0x06070012: "data type does not match, length of service parameter too high",
  0x06070013: "data type does not match, length of service parameter too low",
  0x06090011: "sub-index does not exist",
  0x06090030: "invalid value for parameter",
  0x06090031: "value of parameter written too high",
  0x06090032: "value of parameter written too low",
  0x08000000: "general error",
  0x08000020: "data cannot be transferred or stored to the application",
  0x08000021: "data cannot be transferred because of local control",
  0x08000022: "data cannot be transferred because of the present device state",
};

function abortText(code) {
  const hex = "0x" + (code >>> 0).toString(16).toUpperCase().padStart(8, "0");
  return ABORTS[code] ? hex + " " + ABORTS[code] : hex;
}

function controlResult(r) {
  return L.controlResults[r] || "result " + r;
}

module.exports = { errorText, abortText, controlResult };
