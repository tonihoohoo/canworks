---
name: canworks-datasheet-notes
description: Write canworks device notes (canworks-notes.v1, <eds>.notes.json) for one CANopen device from its datasheet or manual (PDF, DOCX, ODT, HTML, XLSX/CSV, text) and its EDS, for the configurator's Import notes.
---

# Device notes from a datasheet

Write a notes file in the format `canworks-notes.v1` for one EDS, from the device's datasheet or manual. The canworks configurator shows these notes over the EDS: what an object does, its unit and scale, what its values mean and what its bits are. Notes are documentation on the PC only; they never reach a device. The format is in `schema/canworks-notes.v1.schema.json` and `docs/configurator.md` (Device notes).

## Inputs

- **The device's EDS** (required). Note keys must be objects the EDS has, or **Import notes…** skips them. If only a datasheet was given, ask for the EDS; do not guess keys.
- **The datasheet or manual**: PDF (also scanned), DOCX, ODT, HTML or a web page, XLSX or CSV object lists, plain text or Markdown. Several files are fine (datasheet plus manual).
- Optional: the config folder (`canworks/`) the EDS is in, to write the result next to it.

The commands below come with the canworks PC tools (`canworks-deploy`). If it is not installed, say so and stop.

## Steps

1. **What to describe and what is already there.**
   - `canworks-deploy notes skeleton <eds>`: every manufacturer object and sub-object (0x2000-0x5FFF) with its EDS name, data type (`x-type`) and access (`x-access`).
   - `canworks-deploy notes builtin <eds>`: the built-in CiA 301 notes, plus CiA 401 or 402 by the EDS's device type. Do not repeat these.
   Also read the EDS itself for the standard objects (0x1000-0x1FFF, 0x6000-0x9FFF) the device has.

2. **Find the object dictionary in the datasheet.** Do not convert the whole document to Markdown first; make a text copy only to search it:
   - PDF: `pdftotext -layout file.pdf -`. Search for the indices as datasheets write them: `2010h`, `0x2010`, `2010 sub 2`, `2010.02`, `Index 2010`, `2010:02`. Then **read the pages you found yourself** (as PDF pages, or as images for scanned pages), because bit tables, merged cells and value lists come out wrong in a text dump, and you need the page numbers.
   - DOCX, ODT, HTML or a web page: `pandoc -t gfm` keeps headings and tables; read that Markdown copy. Use section numbers where there are no pages.
   - XLSX or CSV: read the sheets as tables (one row per object is common).
   - Text or Markdown: read as is.

3. **Compare with the EDS and collect differences** for every object you would describe: an object or sub-index only in one of them, another data type or size, another access, another range or default. Do not write yet.

4. **Ask about each difference, one at a time,** before writing the file. Show the object, what the EDS says, and what the datasheet says with its page or section. Offer:
   - **Follow EDS**: the note matches the EDS.
   - **Use datasheet**: the datasheet's description, with the difference stated in `details`.
   - **Skip**: no note for this object.
   Each question also offers **same for the rest of this kind** (for example every sub-index of one array shifted by one), so the user is not asked the same thing many times. An object only in the datasheet gets no key whatever the answer (a note cannot add an object to the EDS); ask only so the report can say what to fix. Do not ask about objects the datasheet simply does not describe.

5. **Write the notes.** Only what the datasheet states; leave a field out rather than guess it.
   - Keys: `0x2010` for a VAR or a whole ARRAY/RECORD, `0x2011:2` for a sub-object, four upper-case hex digits, sub-index in decimal.
   - `text`: one line, at most 200 characters, what the object does. Short summaries in your own words, not copied passages. English unless the user asks for another language.
   - `details`: longer text when it helps: range, when a change takes effect (at once, after a reset, after NMT), dependencies, the EDS difference from step 4.
   - `unit` (at most 20 characters) and `scale` (shown value = raw value × scale, never 0) from the stated resolution: "0.1 bar per digit" is unit `bar`, scale `0.1`.
   - `values`: raw value in **decimal** as a string to its meaning. Convert hex values (`0Ah` is `"10"`).
   - `bits`: bit number (`"0"`-`"63"`) to its name, only on integer objects and never past the object's size.
   - `manual`: on **every** entry, where the datasheet describes it: `p. 42, 6.3.2`, or the section when there are no pages.
   - A sub-object without its own entry uses its object's `text`, `details`, `unit`, `scale` and `manual` (not `values` or `bits`), so put what all sub-objects share on the object key and only the differences on sub-object keys.
   - Standard objects (0x1000-0x1FFF, 0x6000-0x9FFF): only where the datasheet says the device does something the built-in note does not cover, such as its own scaling of an analog input, extra or missing values of a mode object, or manufacturer bits in a status word.
   - Objects the datasheet does not describe: leave them out (no name-only entries). Drop the skeleton's `x-type` and `x-access` and `name` fields from your output.
   - Copy the skeleton's `"eds"` block (file, vendor ID, product code, revision) into the file, so an import into another device or revision warns.

6. **Check:** `canworks-deploy notes check <eds> <notes file>`. Fix every finding and run it again until it prints nothing and exits 0.

7. **Save next to the EDS.** Name it `<EDS file name>.notes.json` (for `valve.eds`: `valve.eds.notes.json`) only if that file does not exist. If it exists, never overwrite or edit it: write `<EDS file name>.datasheet.notes.json` and tell the user to open the node's **Notes** tab in the configurator and use **Import notes…** with it; the preview shows new, changed and unchanged notes, and Ctrl+Z takes the import back.

## Report

Tell the user, briefly:
- the file written and how many objects got notes;
- EDS objects the datasheet does not describe;
- items left out and why (unreadable table, unclear meaning);
- each EDS/datasheet difference and the answer used; those answered **Use datasheet**, and objects only in the datasheet, are places where the EDS may need fixing.

## Example

From a manual saying, on page 42, section 6.3.2, that 0x2011 sub 2 "Fault reaction" (UNSIGNED8) selects 0 = hold position, 1 = close, and that 0x2011 sub 1 is the fault delay in ms:

```json
{
  "format": "canworks-notes.v1",
  "eds": {"file": "valve.eds", "vendor_id": "0x000000AB", "product_code": "0x00001234", "revision": "0x00010002"},
  "objects": {
    "0x2011": {"text": "What the valve does on a bus fault", "manual": "p. 42, 6.3.2"},
    "0x2011:1": {"text": "Delay before the fault reaction", "unit": "ms"},
    "0x2011:2": {"text": "Reaction to a bus fault", "values": {"0": "hold position", "1": "close"}}
  }
}
```
