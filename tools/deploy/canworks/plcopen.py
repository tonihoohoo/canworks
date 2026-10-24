"""PLCopen XML (IEC 61131-10, TC6 XML 2.01) for a PLC other than OpenPLC.

`writer(...)` turns ST sources (the canworks library, the generated
canworks_in and canworks_out) and global variable lists into one TC6 XML
file. Three dialects (plcopen-export spec):

    codesys   named global variable lists as CODESYS `globalvars` addData
              objects, the declarations also as InterfaceAsPlainText (so
              pragmas such as qualified_only survive); no configuration,
              CODESYS keeps its tasks in its own task configuration
    trust     standard TC6 as generic (truST 0.24 cannot assign to an array
              element in a NAMESPACE, which a CODESYS-style list becomes)
    generic   standard TC6 only: a list becomes a STRUCT type and one
              resource global variable of it, so `canworks.ok` reads the
              same in every dialect; one configuration with the task. The
              programs declare it VAR_EXTERNAL (plcopen_targets)

CODESYS gets the tc6_0200 namespace it reads, trust and generic tc6_0201.

Bodies stay plain ST text. The declarations are parsed from the sources
(one declaration per line, as canworks writes them) into TC6 interfaces.
"""

import re
from xml.sax.saxutils import escape, quoteattr

NS = "http://www.plcopen.org/xml/tc6_0200"
# TC6 2.01, the standard dialects' namespace (plcopen-export "Standard globals
# in the generic dialect"); CODESYS reads tc6_0200.
NS_201 = "http://www.plcopen.org/xml/tc6_0201"
NAMESPACES = {"codesys": NS, "trust": NS_201, "generic": NS_201}
XHTML = "http://www.w3.org/1999/xhtml"
PLAINTEXT = "http://www.3s-software.com/plcopenxml/interfaceasplaintext"
GLOBALVARS = "http://www.3s-software.com/plcopenxml/globalvars"
DIALECTS = ("codesys", "trust", "generic")

ELEMENTARY = ("BOOL", "BYTE", "WORD", "DWORD", "LWORD", "SINT", "INT", "DINT", "LINT", "USINT", "UINT",
              "UDINT", "ULINT", "REAL", "LREAL", "TIME", "DATE", "DT", "TOD")
_POU_KIND = {"FUNCTION": "function", "FUNCTION_BLOCK": "functionBlock", "PROGRAM": "program"}
_SECTION = {"VAR_INPUT": "inputVars", "VAR_OUTPUT": "outputVars", "VAR_IN_OUT": "inOutVars",
            "VAR": "localVars", "VAR_TEMP": "tempVars", "VAR_EXTERNAL": "externalVars"}
# TC6 order of the interface sections.
_SECTION_ORDER = ("inputVars", "outputVars", "inOutVars", "externalVars", "localVars", "tempVars")


class PlcopenError(ValueError):
    pass


class Var:
    def __init__(self, name, type_, init=None, address=None, doc=""):
        self.name = name
        self.type = type_
        self.init = init
        self.address = address
        self.doc = doc


class Section:
    def __init__(self, keyword, constant=False, variables=None):
        self.keyword = keyword
        self.constant = constant
        self.vars = variables or []


class Pou:
    def __init__(self, kind, name, result=None, sections=None, body="", doc=""):
        self.kind = kind
        self.name = name
        self.result = result
        self.sections = sections or []
        self.body = body
        self.doc = doc

    def declaration_text(self):
        """The POU's head and VAR sections as ST (InterfaceAsPlainText)."""
        head = {"function": "FUNCTION %s : %s" % (self.name, self.result),
                "functionBlock": "FUNCTION_BLOCK %s" % self.name,
                "program": "PROGRAM %s" % self.name}[self.kind]
        return head + "\n" + "".join(_section_text(s) for s in self.sections)


class GlobalList:
    """A named global variable list, read as `<list>.<variable>`. CODESYS
    gets it as a list with the qualified_only pragma; trust and generic get
    a STRUCT type and one global of it (truST 0.24 cannot assign to an
    element of an array in a NAMESPACE)."""

    def __init__(self, name, variables, constant=False, doc=""):
        self.name = name
        self.vars = variables
        self.constant = constant
        self.doc = doc


class Task:
    def __init__(self, name, interval_ms, programs, priority=1):
        self.name = name
        self.interval_ms = interval_ms
        self.programs = programs
        self.priority = priority


# -- ST sources -> POUs ------------------------------------------------------------

def _mask(text):
    """`text` with comments and the insides of string literals blanked out
    (newlines kept), so positions in the result are positions in `text`."""
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        if text.startswith("(*", i):
            end = text.find("*)", i + 2)
            end = n if end < 0 else end + 2
        elif text.startswith("//", i):
            end = text.find("\n", i)
            end = n if end < 0 else end
        elif text[i] in "'\"":
            end = text.find(text[i], i + 1)
            end = n if end < 0 else end + 1
        else:
            i += 1
            continue
        # A string keeps its quotes, so it still reads as a value.
        quoted = text[i] in "'\""
        for k in range(i + quoted, end - quoted):
            if out[k] != "\n":
                out[k] = " "
        i = end
    return "".join(out)


def _comments(text):
    """The comment texts in `text`, joined."""
    parts = []
    for m in re.finditer(r"\(\*(.*?)\*\)|//([^\n]*)", text, re.S):
        body = m.group(1) if m.group(1) is not None else m.group(2)
        lines = [re.sub(r"^\s*\*?\s?", "", ln).rstrip() for ln in body.strip("\n").split("\n")]
        parts.append("\n".join(lines).strip())
    return "\n".join(p for p in parts if p)


_DECL = re.compile(r"^\s*([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s*(?:AT\s+(%\S+)\s*)?:\s*(.+?)"
                   r"(?:\s*:=\s*(.+?))?\s*;\s*$", re.S)


def _parse_vars(text, masked):
    """Variables of one VAR section body: one declaration per line, a comment
    on the line is its documentation."""
    out = []
    lines, mlines = text.split("\n"), masked.split("\n")
    for line, mline in zip(lines, mlines):
        if not mline.strip():
            continue
        m = _DECL.match(mline)
        if m is None:
            raise PlcopenError("cannot read the declaration %r" % line.strip())
        start, end = m.span(3)
        type_ = line[start:end].strip()
        init = line[m.start(4):m.end(4)].strip() if m.group(4) else None
        doc = _comments(line)
        for name in re.split(r"\s*,\s*", m.group(1).strip()):
            out.append(Var(name, type_, init, m.group(2), doc))
    return out


_POU_HEAD = re.compile(r"\b(FUNCTION_BLOCK|FUNCTION|PROGRAM)\s+([A-Za-z_]\w*)(?:[ \t]*:[ \t]*([A-Za-z_][\w\[\]. ]*?))?[ \t]*$",
                       re.M)
_SECTION_RE = re.compile(r"\b(VAR_INPUT|VAR_OUTPUT|VAR_IN_OUT|VAR_TEMP|VAR_EXTERNAL|VAR)\b(\s+CONSTANT\b)?"
                         r"(.*?)\bEND_VAR\b", re.S)


def parse_st(text):
    """[Pou] of an ST source with functions, function blocks and programs.
    A comment before a POU (or right after its head) is its documentation."""
    masked = _mask(text)
    pous = []
    pos = 0
    for head in _POU_HEAD.finditer(masked):
        if head.start() < pos:
            continue
        keyword, name, result = head.group(1), head.group(2), head.group(3)
        end_kw = "END_" + keyword
        end = re.compile(r"\b%s\b" % end_kw).search(masked, head.end())
        if end is None:
            raise PlcopenError("%s %s has no %s" % (keyword, name, end_kw))
        doc = _comments(text[pos:head.start()])
        cursor = head.end()
        sections = []
        first_section = True
        while True:
            m = _SECTION_RE.search(masked, cursor, end.start())
            if m is None or masked[cursor:m.start()].strip():
                break
            if first_section:
                lead = _comments(text[cursor:m.start()])
                doc = "\n".join(p for p in (doc, lead) if p)
                first_section = False
            sections.append(Section(m.group(1), bool(m.group(2)),
                                    _parse_vars(text[m.start(3):m.end(3)], masked[m.start(3):m.end(3)])))
            cursor = m.end()
        body = text[cursor:end.start()].strip("\n")
        body = re.sub(r"^[ \t]*\n", "", body).rstrip()
        pous.append(Pou(_POU_KIND[keyword], name, result.strip() if result else None, sections, body + "\n",
                        doc))
        pos = end.end()
    return pous


# -- TC6 writer --------------------------------------------------------------------------

def _type_xml(type_):
    t = type_.strip()
    u = t.upper()
    if u in ELEMENTARY:
        return "<%s/>" % u
    m = re.match(r"ARRAY\s*\[(.+?)\]\s*OF\s+(.+)$", t, re.I | re.S)
    if m:
        dims = []
        for d in m.group(1).split(","):
            lo, _, hi = d.partition("..")
            dims.append('<dimension lower=%s upper=%s/>' % (quoteattr(lo.strip()), quoteattr(hi.strip())))
        return "<array>%s<baseType>%s</baseType></array>" % ("".join(dims), _type_xml(m.group(2)))
    m = re.match(r"(W?STRING)\s*(?:\[\s*(\d+)\s*\]|\(\s*(\d+)\s*\))?$", t, re.I)
    if m:
        size = m.group(2) or m.group(3)
        tag = m.group(1).lower()
        return "<%s%s/>" % (tag, ' length="%s"' % size if size else "")
    if not re.match(r"[A-Za-z_]\w*$", t):
        raise PlcopenError("cannot write the type %r" % t)
    return '<derived name=%s/>' % quoteattr(t)


def _doc_xml(doc, indent):
    if not doc:
        return ""
    return '%s<documentation><xhtml xmlns="%s">%s</xhtml></documentation>\n' % (indent, XHTML, escape(doc))


def _var_xml(v, indent):
    attrs = "name=%s" % quoteattr(v.name)
    if v.address:
        attrs += " address=%s" % quoteattr(v.address)
    inner = "%s  <type>%s</type>\n" % (indent, _type_xml(v.type))
    if v.init is not None:
        inner += "%s  <initialValue><simpleValue value=%s/></initialValue>\n" % (indent, quoteattr(v.init))
    inner += _doc_xml(v.doc, indent + "  ")
    return "%s<variable %s>\n%s%s</variable>\n" % (indent, attrs, inner, indent)


def _vars_xml(tag, variables, indent, attrs=""):
    if not variables:
        return "%s<%s%s/>\n" % (indent, tag, attrs)
    return "%s<%s%s>\n%s%s</%s>\n" % (indent, tag, attrs, "".join(_var_xml(v, indent + "  ") for v in variables),
                                      indent, tag)


def _section_text(s):
    kw = s.keyword + (" CONSTANT" if s.constant else "")
    lines = []
    for v in s.vars:
        # The comment goes before the ';': truST's import ends every line
        # of a list's plain text with one.
        doc = " (* %s *)" % v.doc.replace("*)", "* )").replace("\n", " ") if v.doc else ""
        lines.append("  %s%s : %s%s%s;" % (v.name, " AT %s" % v.address if v.address else "", v.type,
                                           " := %s" % v.init if v.init is not None else "", doc))
    return "%s\n%s\nEND_VAR\n" % (kw, "\n".join(lines)) if lines else "%s\nEND_VAR\n" % kw


def _plaintext_xml(text, indent):
    return ('%s<addData><data name="%s" handleUnknown="implementation"><InterfaceAsPlainText>'
            '<xhtml xmlns="%s">%s</xhtml></InterfaceAsPlainText></data></addData>\n'
            % (indent, PLAINTEXT, XHTML, escape(text)))


def _pou_xml(p, plaintext):
    ind = "      "
    out = ["%s<pou name=%s pouType=%s>\n" % (ind, quoteattr(p.name), quoteattr(p.kind)),
           "%s  <interface>\n" % ind]
    if p.result:
        out.append("%s    <returnType>%s</returnType>\n" % (ind, _type_xml(p.result)))
    by_tag = {}
    for s in p.sections:
        by_tag.setdefault((_SECTION[s.keyword], s.constant), []).extend(s.vars)
    for tag in _SECTION_ORDER:
        for constant in (False, True):
            if (tag, constant) in by_tag:
                out.append(_vars_xml(tag, by_tag[(tag, constant)], ind + "    ",
                                     ' constant="true"' if constant else ""))
    out.append("%s  </interface>\n" % ind)
    out.append('%s  <body><ST><xhtml xmlns="%s">%s</xhtml></ST></body>\n' % (ind, XHTML, escape(p.body)))
    if plaintext:
        out.append(_plaintext_xml(p.declaration_text(), ind + "  "))
    out.append(_doc_xml(p.doc, ind + "  "))
    out.append("%s</pou>\n" % ind)
    return "".join(out)


def _list_text(lst):
    return "{attribute 'qualified_only'}\n" + _section_text(Section("VAR_GLOBAL", lst.constant, lst.vars))


def _vendor_list_xml(lst):
    ind = "    "
    out = ['%s<data name="%s" handleUnknown="implementation">\n' % (ind, GLOBALVARS),
           "%s  <globalVars name=%s%s>\n" % (ind, quoteattr(lst.name), ' constant="true"' if lst.constant else "")]
    out += [_var_xml(v, ind + "    ") for v in lst.vars]
    out.append(_plaintext_xml(_list_text(lst), ind + "    "))
    out.append(_doc_xml(lst.doc, ind + "    "))
    out.append("%s  </globalVars>\n%s</data>\n" % (ind, ind))
    return "".join(out)


def _struct_xml(lst):
    ind = "      "
    return ("%s<dataType name=%s>\n%s  <baseType>\n%s    <struct>\n%s%s    </struct>\n%s  </baseType>\n%s%s</dataType>\n"
            % (ind, quoteattr(struct_name(lst)), ind, ind, "".join(_var_xml(v, ind + "      ") for v in lst.vars),
               ind, ind, _doc_xml(lst.doc, ind + "  "), ind))


def struct_name(lst):
    return lst.name + "_values"


def _interval(ms):
    return "T#%dms" % ms


def writer(pous, lists, dialect, tasks=(), name="canworks", product_version="0", created="1970-01-01T00:00:00",
           doc=""):
    """The TC6 XML text of `pous` ([Pou]), `lists` ([GlobalList]) and, for
    trust and generic, one configuration with `tasks` ([Task])."""
    if dialect not in DIALECTS:
        raise PlcopenError("unknown dialect %r" % dialect)
    vendor = dialect == "codesys"
    out = ['<?xml version="1.0" encoding="utf-8"?>\n',
           '<project xmlns="%s">\n' % NAMESPACES[dialect],
           '  <fileHeader companyName="canworks" productName="canworks-deploy" productVersion=%s '
           'creationDateTime=%s/>\n' % (quoteattr(product_version), quoteattr(created)),
           '  <contentHeader name=%s>\n' % quoteattr(name)]
    if doc:
        out.append("    <Comment>%s</Comment>\n" % escape(doc))
    out.append('    <coordinateInfo><fbd><scaling x="1" y="1"/></fbd><ld><scaling x="1" y="1"/></ld>'
               '<sfc><scaling x="1" y="1"/></sfc></coordinateInfo>\n  </contentHeader>\n')
    out.append("  <types>\n")
    structs = [] if vendor else [lst for lst in lists if not lst.constant]
    if structs:
        out.append("    <dataTypes>\n%s    </dataTypes>\n" % "".join(_struct_xml(lst) for lst in structs))
    else:
        out.append("    <dataTypes/>\n")
    out.append("    <pous>\n%s    </pous>\n" % "".join(_pou_xml(p, vendor) for p in pous))
    out.append("  </types>\n")
    if vendor:
        out.append("  <instances><configurations/></instances>\n")
    else:
        out.append("  <instances>\n    <configurations>\n")
        out.append("      <configuration name=\"%s_config\">\n" % name)
        out.append("        <resource name=\"%s_res\">\n" % name)
        for t in tasks:
            out.append("          <task name=%s interval=%s priority=\"%d\">\n"
                       % (quoteattr(t.name), quoteattr(_interval(t.interval_ms)), t.priority))
            for prog in t.programs:
                out.append("            <pouInstance name=%s typeName=%s/>\n"
                           % (quoteattr(prog + "_instance"), quoteattr(prog)))
            out.append("          </task>\n")
        if not vendor:
            for lst in lists:
                if lst.constant:
                    out.append(_vars_xml("globalVars", lst.vars, "          ", ' constant="true"'))
                else:
                    out.append(_vars_xml("globalVars", [Var(lst.name, struct_name(lst), doc=lst.doc)],
                                         "          "))
        out.append("        </resource>\n      </configuration>\n    </configurations>\n  </instances>\n")
    if vendor and lists:
        out.append("  <addData>\n%s  </addData>\n" % "".join(_vendor_list_xml(lst) for lst in lists))
    out.append("</project>\n")
    return "".join(out)
