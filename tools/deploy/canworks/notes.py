"""Device notes (spec canopen-device-notes): a short text, unit, scale, value
meanings and bit names per object of an EDS, for people.

A project keeps one notes file per EDS next to it, `<eds file name>.notes.json`
(format canworks-notes.v1). canworks ships notes in the same format for the
CiA 301 communication objects and the CiA 401 and 402 profiles (builtin_notes/), which
apply by the EDS's 0x1000 device type. The device file holds only what the
user wrote; an object's note is its device entry merged field by field over
its built-in entry. Notes never change what is written to a device: the
deploy tool and the plugin do not read them.
"""

import copy
import json
import os
import re

import jsonschema

from .userdirs import replace_file

FORMAT = "canworks-notes.v1"
SUFFIX = ".notes.json"
FIELDS = ("text", "details", "unit", "scale", "values", "bits", "manual")
INHERITED = ("text", "details", "unit", "scale", "manual")  # what a sub-object takes from its object's entry
MANUFACTURER = (0x2000, 0x5FFF)
PROFILES = (401, 402)

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCHEMA_PATH = os.path.join(_HERE, "schema", "canworks-notes.v1.schema.json")
_BUILTIN_DIR = os.path.join(_HERE, "builtin_notes")
_KEY = re.compile(r"^0x([0-9A-F]{4})(?::(\d{1,3}))?$")

# Objects that repeat over a range share the built-in note of the range's
# first object: SDO server/client and PDO communication and mapping.
TEMPLATES = ((0x1200, 0x127F), (0x1280, 0x12FF), (0x1400, 0x15FF), (0x1600, 0x17FF), (0x1800, 0x19FF),
             (0x1A00, 0x1BFF))

# Objects whose sub-objects 1-254 all share the built-in note of sub 1.
SUB_TEMPLATES = (0x1003, 0x1016, 0x1600, 0x1A00, 0x1F51, 0x1F81, 0x6421, 0x6443)

_schema = None
_builtin_files = {}


class NotesError(Exception):
    pass


def notes_path(eds_path):
    """The notes file of an EDS file."""
    return eds_path + SUFFIX


def key(index, sub=None):
    return "0x%04X" % index if sub is None else "0x%04X:%d" % (index, sub)


def parse_key(text):
    """(index, sub or None) of a notes key, or None when it is not one."""
    m = _KEY.match(text) if isinstance(text, str) else None
    if not m or (m.group(2) is not None and int(m.group(2)) > 255):
        return None
    return int(m.group(1), 16), int(m.group(2)) if m.group(2) is not None else None


def schema():
    global _schema
    if _schema is None:
        with open(_SCHEMA_PATH, encoding="utf-8") as f:
            _schema = json.load(f)
    return _schema


def schema_problems(data):
    """The schema findings of a notes document, as "where: message" texts."""
    validator = jsonschema.Draft202012Validator(schema())
    out = []
    for e in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in e.absolute_path)
        out.append(("%s: %s" % (where, e.message)) if where else e.message)
    return out


def load_text(text, name="notes"):
    """(notes document, error text or None) from a notes file's text. A file
    that is not JSON or has another format gives (None, error)."""
    try:
        data = json.loads(text)
    except ValueError as e:
        return None, "%s cannot be read: %s" % (name, e)
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        return None, "%s is not a %s file" % (name, FORMAT)
    if not isinstance(data.get("objects"), dict):
        return None, "%s has no objects map" % name
    return data, None


def load(path):
    """(notes document or None, error or None). A missing file is (None, None)."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return None, None
    except (OSError, UnicodeDecodeError) as e:
        return None, "%s cannot be read: %s" % (os.path.basename(path), e)
    return load_text(text, os.path.basename(path))


def _builtin_file(name):
    if name not in _builtin_files:
        with open(os.path.join(_BUILTIN_DIR, name + ".json"), encoding="utf-8") as f:
            _builtin_files[name] = json.load(f)
    return _builtin_files[name]


def profile(eds):
    """The device profile number from the EDS's 0x1000 default (low 16 bits), or None."""
    o = eds.find(0x1000, 0)
    v = o.value(1) if o is not None else None
    return v & 0xFFFF if isinstance(v, int) else None


def builtin_sets(eds):
    """(the built-in note sets that apply to this EDS, e.g. ["CiA 301",
    "CiA 402"], and a note naming a device profile without built-in notes,
    or None)."""
    sets = ["CiA 301"]
    p = profile(eds)
    if p in PROFILES:
        sets.append("CiA %d" % p)
        return sets, None
    if p is None:
        return sets, "0x1000 has no device type default, so no profile notes apply"
    if p == 0:
        return sets, None
    return sets, "there are no built-in notes for profile %d" % p


def _template(index):
    for lo, hi in TEMPLATES:
        if lo <= index <= hi:
            return lo
    return index


def builtin(eds):
    """{key: note} of the built-in notes that apply to this EDS, for the
    objects it has. Range objects (PDO, SDO parameters) get their range's
    note under their own index."""
    tables = [_builtin_file("cia301")["objects"]]
    p = profile(eds)
    if p in PROFILES:
        tables.append(_builtin_file("cia%d" % p)["objects"])
    out = {}
    for index in sorted(eds.objects):
        source = _template(index)
        for table in tables:
            for k, v in table.items():
                ix, sub = parse_key(k)
                if ix != source:
                    continue
                if sub is None:
                    out[key(index)] = copy.deepcopy(v)
                elif sub == 1 and source in SUB_TEMPLATES:
                    for s in eds.objects[index]:
                        if s == 1 or (s > 1 and key(source, s) not in table):
                            out[key(index, s)] = copy.deepcopy(v)
                elif sub in eds.objects[index]:
                    out[key(index, sub)] = copy.deepcopy(v)
    return out


def _is_var(eds, index):
    return eds.object_types.get(index, 0x7) == 0x7


def _layer(table, eds, index, sub):
    """One table's note of a sub-object, with what it inherits from its
    object's entry. {} when the table has nothing for it."""
    own = table.get(key(index, sub)) if sub is not None else None
    obj = table.get(key(index))
    if _is_var(eds, index) and sub == 0:
        out = dict(obj or {})
        if own:
            out.update(own)
        return out
    out = {f: obj[f] for f in INHERITED if obj and f in obj}
    if own:
        out.update(own)
    return out


def note(eds, builtin_table, device_table, index, sub):
    """The merged note of a sub-object: device over built-in, field by field,
    each with its own inheritance from the object. A device field of None
    (null in the file) clears the field. Only FIELDS are kept."""
    out = _layer(builtin_table or {}, eds, index, sub)
    out.update(_layer(device_table or {}, eds, index, sub))
    return {f: out[f] for f in FIELDS if f in out and out[f] not in ("", None)}


class Notes:
    """The notes of one EDS: built-in, the device file's (when readable) and
    the file's problems."""

    def __init__(self, eds, eds_name, path=None, device=None, error=None):
        self.eds, self.eds_name, self.path = eds, eds_name, path
        self.builtin = builtin(eds)
        self.document = device
        self.device = (device or {}).get("objects") or {}
        self.error = error

    @classmethod
    def for_eds(cls, eds, eds_name, eds_path=None):
        """The notes of an EDS file: its notes file next to it, when there is one."""
        path = notes_path(eds_path) if eds_path else None
        doc, error = load(path) if path else (None, None)
        return cls(eds, eds_name, path, doc, error)

    def edited(self, changes):
        """These notes with the page's unsaved edits of the device file."""
        if changes and self.error is None:
            self.device = apply_changes(self.device, changes)
        return self

    def note(self, index, sub, overrides=None):
        device = self.device
        if overrides:
            device = apply_changes(device, overrides)
        return note(self.eds, self.builtin, device, index, sub)

    def merged(self, overrides=None):
        """{key: merged note} of every sub-object that has one (VAR objects
        under their object key)."""
        device = apply_changes(self.device, overrides) if overrides else self.device
        out = {}
        for index, sub, _ in self.eds.items():
            n = note(self.eds, self.builtin, device, index, sub)
            if n:
                out[key(index) if _is_var(self.eds, index) and sub == 0 else key(index, sub)] = n
        return out

    def merged_document(self):
        doc = {"format": FORMAT, "eds": identity(self.eds_name, self.eds_path_info()), "objects": self.merged()}
        return doc

    def eds_path_info(self):
        return self.path[:-len(SUFFIX)] if self.path else None

    def to_json(self):
        """For the configurator page: the two tables, the file and its problem."""
        return {"builtin": self.builtin, "device": self.device, "file": os.path.basename(self.path) if self.path else None,
                "exists": self.document is not None, "error": self.error, "profile": profile(self.eds)}


def identity(eds_name, eds_path=None, text=None):
    from .eds import device_info, device_info_text
    info = device_info_text(text, eds_name) if text is not None else device_info(eds_path) if eds_path else None
    out = {"file": eds_name}
    for k, field in (("vendor_id", "vendor_id"), ("product_code", "product_code"), ("revision", "revision_number")):
        v = (info or {}).get(field)
        if v is not None:
            out[k] = "0x%08X" % v
    return out


def type_text(o):
    """The data type name of a sub-object, for messages and `x-type`."""
    return o.type_name or OTHER_TYPES.get(o.data_type, "0x%04X" % o.data_type)


IDENTITY_FIELDS = (("vendor_id", "vendor ID"), ("product_code", "product code"), ("revision", "revision"))


def missing_identity(identity_):
    """The names of the identity fields (vendor ID, product code, revision) an
    EDS identity lacks."""
    return [text for k, text in IDENTITY_FIELDS if k not in identity_]


def skeleton(eds, eds_name, eds_text=None, eds_path=None, describe=False, all_objects=False, indices=None):
    """A new notes document: the EDS identity and an entry with only `name`
    for every manufacturer object and sub-object. With `describe`, each
    entry also has the EDS data type (`x-type`) and access (`x-access`),
    for `canworks-deploy notes skeleton`. With `all_objects` it has every
    object of the EDS, an entry with the name of each ARRAY and RECORD
    object itself, and the EDS default, limits and PDO mapping
    (`x-default`, `x-low`, `x-high`, `x-pdo`) as the EDS writes them.
    `indices` (low, high) keeps only the objects in that range."""
    lo, hi = indices or ((0, 0xFFFF) if all_objects else MANUFACTURER)
    objects = {}
    for index, sub, o in eds.items():
        if not lo <= index <= hi or not (all_objects or MANUFACTURER[0] <= index <= MANUFACTURER[1]):
            continue
        if all_objects and not _is_var(eds, index) and sub == min(eds.objects[index]):
            objects[key(index)] = {"name": eds.names.get(index, "")}
        entry = {"name": o.name}
        if describe:
            entry.update({"x-type": type_text(o), "x-access": o.access})
        if all_objects:
            for field, value in (("x-default", o.default), ("x-low", o.low_limit), ("x-high", o.high_limit)):
                if value:
                    entry[field] = value
            entry["x-pdo"] = bool(o.pdo_mapping)
        objects[key(index) if _is_var(eds, index) else key(index, sub)] = entry
    return {"format": FORMAT, "eds": identity(eds_name, eds_path, eds_text), "objects": objects}


def apply_changes(objects, changes):
    """objects with the page's edits: {key: note} replaces an entry's fields
    (fields not given are removed, other keys such as hand-written extras are
    kept; a field of None clears the built-in field), {key: None} removes the
    entry."""
    out = dict(objects or {})
    for k, v in (changes or {}).items():
        if parse_key(k) is None:
            continue
        if v is None:
            out.pop(k, None)
            continue
        entry = {kk: vv for kk, vv in (out.get(k) or {}).items() if kk not in FIELDS}
        entry.update({f: v[f] for f in FIELDS if f in v and v[f] != ""})
        out[k] = entry
    return out


def filled(entry):
    """Whether a device entry holds a note of the user's: any note field, a
    cleared one (None) included, not only the `name` the skeleton writes."""
    return isinstance(entry, dict) and any(f in entry and entry[f] != "" for f in FIELDS)


def own_objects(objects):
    """The filled entries of a device table, in their order."""
    return {k: v for k, v in (objects or {}).items() if filled(v)}


def _builtin_layer(eds, builtin_table, index, sub):
    """The built-in note a key stands for: a VAR's object key is its sub 0, a
    record's object key its own entry."""
    if sub is None:
        return _layer(builtin_table, eds, index, 0) if _is_var(eds, index) else dict(builtin_table.get(key(index)) or {})
    return _layer(builtin_table, eds, index, sub)


def _differs(identity_, other):
    """None when two EDS identities agree, else "device" or "revision"."""
    if not isinstance(other, dict):
        return None
    for k in ("vendor_id", "product_code"):
        if other.get(k) and identity_.get(k) and str(other[k]).upper() != str(identity_[k]).upper():
            return "device"
    if other.get("revision") and identity_.get("revision") and str(other["revision"]).upper() != str(identity_["revision"]).upper():
        return "revision"
    return None


def plan_import(eds, notes_, doc, identity_=None):
    """What importing the notes document `doc` would do to `notes_` (a Notes
    with the page's edits): (changes {key: entry} for the page's draft,
    preview {new, changed, same, skipped: [key]}, warnings). Fields equal to
    the built-in note or to the note as it is now, and `name`, are not
    imported; an imported field replaces that field of the entry and its
    other fields stay."""
    changes = {}
    preview = {"new": [], "changed": [], "same": [], "skipped": []}
    for k, v in sorted((doc.get("objects") or {}).items(), key=lambda kv: _sort_key(kv[0])):
        pk = parse_key(k)
        if pk is None or not isinstance(v, dict):
            preview["skipped"].append(k)
            continue
        ix, sub = pk
        if ix not in eds.objects or (sub is not None and sub not in eds.objects[ix]):
            preview["skipped"].append(k)
            continue
        base = _builtin_layer(eds, notes_.builtin, ix, sub)
        now = notes_.note(ix, 0 if sub is None else sub) if sub is not None or _is_var(eds, ix) else dict(notes_.device.get(k) or {})
        old = notes_.device.get(k) or {}
        got = {f: v[f] for f in FIELDS if v.get(f) not in ("", None) and v[f] != base.get(f) and v[f] != now.get(f)}
        # A cleared field (null) only where something shows it and it is not cleared already.
        got.update({f: None for f in FIELDS if f in v and v[f] is None and not (f in old and old[f] is None)
                    and (base.get(f) is not None or now.get(f) is not None)})
        if not got:
            preview["same"].append(k)
            continue
        entry = {f: old[f] for f in FIELDS if f in old and old[f] != ""}
        entry.update(got)
        changes[k] = entry
        preview["changed" if filled(old) else "new"].append(k)
    warnings = []
    other = _differs(identity_ or {}, doc.get("eds"))
    if other == "device":
        warnings.append("This notes file was made for another device (%s)" % (doc["eds"].get("file") or "other EDS"))
    elif other == "revision":
        warnings.append("This notes file was made for another revision of this device")
    return changes, preview, warnings


def _sort_key(k):
    ix, sub = parse_key(k) or (0x10000, None)
    return ix, -1 if sub is None else sub


def update(doc, changes, eds):
    """A notes document after the page's edits, with `name` refreshed from the
    EDS. Entries are kept in their order; new ones go in index order."""
    objects = doc.get("objects") or {}
    new = apply_changes(objects, changes)
    added = sorted((k for k in new if k not in objects), key=_sort_key)
    ordered = {}
    for k in list(objects) + added:
        if k not in new:
            continue
        entry = new[k]
        pk = parse_key(k)
        if pk:
            ix, sub = pk
            o = eds.find(ix, 0 if sub is None else sub)
            if o is not None and o.name:
                entry = dict(entry)
                if "name" in entry or k in added:
                    entry = {"name": o.name, **{kk: vv for kk, vv in entry.items() if kk != "name"}}
        ordered[k] = entry
    out = dict(doc)
    out["format"] = FORMAT
    out["objects"] = ordered
    return out


def dumps(doc):
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def access(eds_path, block=None):
    """{"editable", "why"} of the notes file of an EDS file, for a page that
    writes notes at once (Commission a device): no notes file (a built EDS),
    an unreadable one, or a folder or file that cannot be written is
    read-only, with why."""
    if not eds_path:
        return {"editable": False, "why": "this EDS gets canworks' built-in notes only"}
    if block and block.get("error"):
        return {"editable": False, "why": block["error"]}
    path = notes_path(eds_path)
    folder = os.path.dirname(path) or "."
    if (os.path.exists(path) and not os.access(path, os.W_OK)) or not os.access(folder, os.W_OK):
        return {"editable": False, "why": "%s cannot be written in %s" % (os.path.basename(path), folder)}
    return {"editable": True, "why": None}


def write(eds, eds_name, eds_text, eds_path, changes=None, restore=False, text=None):
    """Writes the notes file of an EDS at once (Commission a device): the
    page's changes over the file, or a new file from the skeleton, with the
    same rules as the configurator's Save. With `restore`, puts back `text`
    (an earlier file; None removes the file). Returns the file's text before."""
    path = notes_path(eds_path)
    try:
        with open(path, encoding="utf-8") as f:
            before = f.read()
    except FileNotFoundError:
        before = None
    if restore:
        if text is None:
            if before is not None:
                os.remove(path)
            return before
        _doc, error = load_text(text, os.path.basename(path))
        if error:
            raise NotesError(error)
        new_text = text
    else:
        if before is not None:
            doc, error = load_text(before, os.path.basename(path))
            if error:
                raise NotesError(error + "; it is not changed")
        else:
            doc = skeleton(eds, eds_name, eds_text=eds_text)
        new_text = dumps(update(doc, changes, eds))
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        f.write(new_text)
    replace_file(path + ".tmp", path)
    return before


# Data types the IEC type table leaves out, for messages.
OTHER_TYPES = {0x0009: "VISIBLE_STRING", 0x000A: "OCTET_STRING", 0x000B: "UNICODE_STRING",
               0x000C: "TIME_OF_DAY", 0x000D: "TIME_DIFFERENCE", 0x000F: "DOMAIN",
               0x0010: "INTEGER24", 0x0012: "INTEGER40", 0x0013: "INTEGER48", 0x0014: "INTEGER56",
               0x0016: "UNSIGNED24", 0x0018: "UNSIGNED40", 0x0019: "UNSIGNED48", 0x001A: "UNSIGNED56"}


def _bits_of(type_name):
    m = re.match(r"^(INTEGER|UNSIGNED)(\d+)$", type_name or "")
    return int(m.group(2)) if m else None


def _clears(eds, builtin_table, objects, index, sub, field):
    """Whether a field set to None on this key hides something: a built-in
    value, or one inherited from the device's object entry."""
    if sub is None and not _is_var(eds, index):
        if field not in INHERITED:
            return False
        return (builtin_table.get(key(index)) or {}).get(field) is not None or any(
            (builtin_table.get(key(index, s)) or {}).get(field) is not None for s in eds.objects[index])
    s = 0 if sub is None else sub
    if _layer(builtin_table, eds, index, s).get(field) is not None:
        return True
    obj = objects.get(key(index)) if sub is not None and not _is_var(eds, index) else None
    return field in INHERITED and isinstance(obj, dict) and obj.get(field) is not None


def check(eds, doc, notes_name, eds_name):
    """The warnings of a notes document against the schema and its EDS."""
    out = ["%s: %s" % (notes_name, p) for p in schema_problems(doc)]
    builtin_table = builtin(eds)
    objects_ = doc.get("objects") or {}
    for k, v in objects_.items():
        pk = parse_key(k)
        if pk is None or not isinstance(v, dict):
            continue
        ix, sub = pk
        if ix not in eds.objects or (sub is not None and sub not in eds.objects[ix]):
            out.append("%s has a note for %s, which %s does not have" % (notes_name, k, eds_name))
            continue
        subs = [eds.objects[ix][sub]] if sub is not None else (
            [eds.objects[ix][0]] if _is_var(eds, ix) else [])
        for field in FIELDS:
            if field in v and v[field] is None and not _clears(eds, builtin_table, objects_, ix, sub, field):
                out.append("%s: %s clears its %s, but there is none to clear" % (notes_name, k, field))
        if sub is None and not _is_var(eds, ix):
            for field in ("values", "bits"):
                if v.get(field) is not None:
                    out.append("%s: the %s of %s are not used by its sub-objects; write them on its sub-object keys"
                               % (notes_name, field, k))
        for o in subs:
            bits = _bits_of(type_text(o))
            for field in ("values", "bits"):
                if v.get(field) is not None and bits is None and not (field == "values" and o.type_name == "BOOLEAN"):
                    out.append("%s: %s has %s, but its type %s is not an integer type"
                               % (notes_name, k, field, type_text(o)))
            if bits is not None and isinstance(v.get("bits"), dict):
                over = sorted(int(b) for b in v["bits"] if str(b).isdigit() and int(b) >= bits)
                if over:
                    out.append("%s: %s names bit %d, but %s has only %d bits" % (notes_name, k, over[0], type_text(o), bits))
        if v.get("scale") == 0:
            out.append("%s: %s has a scale of 0" % (notes_name, k))
    return out


def value_meaning(note_, raw):
    """What a raw value means by a merged note: its name from `values`, else
    the scaled value with its unit ("12.34 bar") or the value with its unit,
    else ""."""
    if raw is None or isinstance(raw, bool):
        return ""
    values = note_.get("values") or {}
    if isinstance(raw, int) and str(raw) in values:
        return values[str(raw)]
    unit, scale = note_.get("unit") or "", note_.get("scale")
    if isinstance(scale, (int, float)) and not isinstance(scale, bool) and scale not in (0, 1) \
            and isinstance(raw, (int, float)):
        return (_fmt(raw * scale) + (" " + unit if unit else ""))
    if unit:
        return "%s %s" % (_fmt(raw), unit)
    return ""


def value_text(note_, raw):
    """`raw (meaning)` of a raw value by a merged note, or the raw value."""
    if raw is None:
        return ""
    what = value_meaning(note_, raw)
    return "%s (%s)" % (_fmt(raw), what) if what else _fmt(raw)


def _fmt(x):
    if isinstance(x, float):
        return "%.6g" % x
    return str(x)
