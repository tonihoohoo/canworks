"use strict";
// Starts the page once every script is loaded (app.js and the files after it).
wire();
loadState().catch((e) => banner(e.message, true));
