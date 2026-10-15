---
name: canworks-datasheet-notes
description: Write canworks device notes (canworks-notes.v1, <eds>.notes.json) for one CANopen device from its datasheet or manual (PDF, DOCX, ODT, HTML, XLSX/CSV, text) and its EDS, for the configurator's Import notes.
---

# Device notes from a datasheet

Write a notes file in the format `canworks-notes.v1` for one EDS, from the device's datasheet or manual. The canworks configurator shows these notes over the EDS: what an object does, its unit and scale, what its values mean and what its bits are. Notes are documentation on the PC only; they never reach a device. The format is described in the canworks docs (`docs/configurator.md`, Device notes) and its schema `canworks-notes.v1.schema.json` comes with the PC tools.

## Inputs

- **The device's EDS** (required). Note keys must be objects the EDS has, or **Import notes…** skips them. If only a datasheet was given, ask for the EDS; do not guess keys.
- **The datasheet or manual**: PDF (also scanned), DOCX, ODT, HTML or a web page, XLSX or CSV object lists, plain text or Markdown. Several files are fine (a CANopen manual plus a parameter manual, a datasheet plus a manual).
- Optional: the config folder (`canworks/`) the EDS is in, to write the result next to it.

The commands below come with the canworks PC tools (`canworks-deploy`). If it is not installed, say so and stop.

## Steps

1. **Read the EDS through the tools.**
   - `canworks-deploy notes skeleton --all <eds>`: every object and sub-object with its EDS name, type (`x-type`), access (`x-access`), default (`x-default`), limits (`x-low`, `x-high`) and PDO mapping (`x-pdo`), as the EDS writes them, and an entry with the name of each ARRAY and RECORD object. Compare against this, not against your own parse of the EDS. For a large EDS, take one range at a time: `canworks-deploy notes skeleton --all --index 0x3000-0x30FF <eds>`.
   - `canworks-deploy notes builtin <eds>`: the built-in notes that apply. Its stderr line names the sets used (CiA 301, plus CiA 401 or 402 by the device type) and says when the device's profile has no built-in notes.
   - **If either command refuses the EDS, stop.** Tell the user the error with its line or section, write no notes file, and do not change or patch the EDS; the configurator refuses the same file.
   - A stderr line saying the EDS gives no product code (or vendor ID, revision): mention it in the report; the import then cannot warn about another device.

2. **Find the object dictionary in the datasheet.** Do not convert the whole document to Markdown first; make a text copy only to search it:
   - PDF: `pdftotext -layout file.pdf -`. Search for the indices as datasheets write them: `2010h`, `0x2010`, `2010 sub 2`, `2010.02`, `Index 2010`, `2010:02`. Then **read the pages you found yourself** (as PDF pages, or as images for scanned pages), because bit tables, merged cells and value lists come out wrong in a text dump. Note both the printed page number and the PDF page.
   - DOCX, ODT, HTML or a web page: `pandoc -t gfm` keeps headings and tables; read that Markdown copy. Use section numbers or headings where there are no pages.
   - XLSX or CSV: read the sheets as tables (one row per object is common).
   - Text or Markdown: read as is.
   - **Index rules.** When the datasheet gives a rule instead of indices (index = base + parameter number, process and parameter objects, sub-index in hex), apply it to find the EDS key. Write nothing from the rule alone; a note needs the parameter's own description.
   - **Family manuals** covering several variants: describe only what applies to the EDS's device; objects of other variants are not differences.
   - **Manuals for several buses**: objects marked for another bus only are not differences, unless the EDS has them (then they are a row of the table).

3. **Compare with the EDS and collect differences** for every object the datasheet describes: an object or sub-index only in one of them, another name, data type, size, access, range, default or PDO mapping, sub 0 (number of entries) included. An EDS without a default against a datasheet default is a difference. Access written `RW/S`, `RW (stored)` and the like equals `rw`. A table row with only name, type and default is not a description: such objects get no note, but their differences still count. Do not write yet.
   - **Contradictions inside the datasheet** (two tables disagree, a row copied from another object): prefer the detailed section over the summary table, say so in `details`, and list it in the report.

4. **Show all differences in one table, then wait for the answer.** One row per difference, or per group of differences of the same kind (for example "sub 0 default 3 instead of 2" on 0x6064, 0x606C and 0x60FF), listing the objects the row covers. Columns: row number, objects, what the EDS says, what the datasheet says with its page or section, answer. Every row's answer is **Follow EDS** to start with. Ask the user to accept the table or to change rows ("row 3: use datasheet", "row 5: skip"; a group can be split by naming objects):
   - **Follow EDS**: the note keeps the EDS's layout, type, size and range, uses the datasheet's wording where it fits, and states nothing the EDS contradicts; `details` names the difference. A shifted array is written under the EDS's sub-indices.
   - **Use datasheet**: the datasheet's description, with the difference stated in `details`.
   - **Skip**: no note for these objects.
   An object only in the datasheet gets no key whatever the answer (a note cannot add an object to the EDS); its row is there for the report. Do not write until the user has answered. Without any difference, say so and go on.

5. **Write the notes.** Only what the datasheet states; leave a field out rather than guess it.
   - Keys: `0x2010` for a VAR or a whole ARRAY/RECORD, `0x2011:2` for a sub-object, four upper-case hex digits, sub-index in decimal (convert a hex sub-index: `10h` is `:16`).
   - `text`: one line, at most 200 characters, what the object does. Short summaries in your own words, not copied passages. English unless the user asks for another language. From a spreadsheet with many rows, `text` may be the parameter's name in the sheet.
   - `details`: longer text when it helps: range, value ranges and reserved values, fields of several bits, write signatures, a scale that depends on another object, whether the value is stored and when a change takes effect (at once, after a reset, after NMT), objects outside the EDS it needs (such as an enable object), the EDS difference from step 4.
   - `unit` (at most 20 characters) and `scale` (shown value = raw value × scale, never 0) from the stated resolution: "0.1 bar per digit" is unit `bar`, scale `0.1`. A scale derived from a stated full-scale value (0x7FFFFFFF = 10000 rpm) is allowed when `details` says so. No unit that only the object's name implies.
   - `values`: raw value in **decimal** as a string to its meaning, as the EDS object reads it: convert hex (`0Ah` is `"10"`), signed types' hex as negative decimal (`FFFFh` on INTEGER16 is `"-1"`), and one entry per raw value when one row covers several.
   - `bits`: bit number (`"0"`-`"63"`) to its name, only on integer objects and never past the object's size. Bits numbered from 1 in the datasheet are shifted to start at 0, and `details` says so.
   - `values` and `bits` go on sub-object keys or VAR keys, never on an ARRAY or RECORD key: sub-objects do not inherit them.
   - A sub-object without its own entry uses its object's `text`, `details`, `unit`, `scale` and `manual` (not `values` or `bits`), so put what all sub-objects share on the object key and only the differences on sub-object keys. Put `unit` and `scale` on the sub-objects instead when sub 0 (the count) or a sub-object packing two values would otherwise inherit them.
   - `manual`: on **every** entry, where the datasheet describes it: the printed page and section, `p. 27, 4.3`, with the PDF page when it differs, `p. 27 (PDF 28), 4.3`; the section or heading when there are no pages. With several documents, start with the document's number or short title: `BA 0123, p. 18`. From a spreadsheet, name the sheet and the parameter's code, not the row: `sheet Parameters, RAMP`.
   - **Standard objects** (0x1000-0x1FFF, 0x6000-0x9FFF), when a built-in note applies: write a note only where the datasheet says something the built-in note does not cover, such as the device's own scaling, extra or missing values or manufacturer bits in a status word. A device note's `bits`, `values`, `text` and `details` **replace** the built-in field as a whole: write the device's complete list, keeping the built-in entries the datasheet does not contradict (for example the built-in name of a statusword bit the datasheet does not mention).
   - **Built-in notes that do not fit the device**: compare each built-in note of a standard object the datasheet describes. Where it does not fit (a limit in thousandths of rated current where the built-in note says torque), write the device's own `text`, `unit` or `values`. Where the device supports none of a built-in list (no homing, yet built-in homing methods), say so in `text`, and in `details` that the listed values do not apply: a note cannot remove a built-in field.
   - **No built-in notes for the profile** (`notes builtin` says so, for example CiA 404, 406 or 410): standard objects get a note where the datasheet describes them beyond name, type and default.
   - Objects the datasheet does not describe: leave them out (no name-only entries). Drop the skeleton's `name` and `x-` fields from your output.
   - Copy the skeleton's `"eds"` block (file, vendor ID, product code, revision) into the file, so an import into another device or revision warns.

6. **Check:** `canworks-deploy notes check <eds> <notes file>`. Fix every finding and run it again until it prints nothing and exits 0.

7. **Save next to the EDS.** Name it `<EDS file name>.notes.json` (for `valve.eds`: `valve.eds.notes.json`) only if that file does not exist. If it exists, never overwrite or edit it: write `<EDS file name>.datasheet.notes.json` and tell the user to open the node's **Notes** tab in the configurator and use **Import notes…** with it. The preview shows new, changed and unchanged notes; changed rows may be notes the user wrote, so they should check those rows before importing. Ctrl+Z takes the import back.

## Report

Tell the user, briefly:
- the file written and how many objects got notes, and the built-in sets the device has (or that its profile has none);
- EDS objects the datasheet does not describe;
- items left out and why (unreadable table, unclear meaning);
- contradictions inside the datasheet and which side was used;
- the difference table with the answer used for each row; rows answered **Use datasheet**, and objects only in the datasheet, are places where the EDS may need fixing;
- **Other EDS problems seen**: differences on objects that got no note (a device type default, identity sub 0, PDO COB-ID access), and identity fields the EDS lacks.

## Example

From a manual saying, on printed page 42 (PDF 43), section 6.3.2, that 0x2011 sub 2 "Fault reaction" (UNSIGNED8) selects 0 = hold position, 1 = close, and that 0x2011 sub 1 is the fault delay in ms:

```json
{
  "format": "canworks-notes.v1",
  "eds": {"file": "valve.eds", "vendor_id": "0x000000AB", "product_code": "0x00001234", "revision": "0x00010002"},
  "objects": {
    "0x2011": {"text": "What the valve does on a bus fault", "manual": "p. 42 (PDF 43), 6.3.2"},
    "0x2011:1": {"text": "Delay before the fault reaction", "unit": "ms"},
    "0x2011:2": {"text": "Reaction to a bus fault", "values": {"0": "hold position", "1": "close"}}
  }
}
```

A difference table before writing:

| Row | Objects | EDS | Datasheet | Answer |
|---|---|---|---|---|
| 1 | 0x2011:1 | range 0-1000 | 0-5000 ms (p. 42) | Follow EDS |
| 2 | 0x2012 | not in the EDS | fault counter (p. 43) | Follow EDS (no note; report as EDS fix) |
