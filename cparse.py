"""Tiny C tokenizer + function finder (fallback when lizard is unavailable,
and shared by the similarity / readability / modularity analyzers)."""
import bisect
import re

KEYWORDS = {
    "auto", "break", "case", "char", "const", "continue", "default", "do", "double",
    "else", "enum", "extern", "float", "for", "goto", "if", "inline", "int", "long",
    "register", "restrict", "return", "short", "signed", "sizeof", "static", "struct",
    "switch", "typedef", "union", "unsigned", "void", "volatile", "while", "_Bool",
}
CONTROL = {"if", "for", "while", "switch", "return", "sizeof"}

_TOKEN_RE = re.compile(r'''
  (?P<comment>//[^\n]*|/\*.*?\*/)
 |(?P<str>"(?:\\.|[^"\\\n])*")
 |(?P<chr>'(?:\\.|[^'\\\n])+')
 |(?P<pre>^[ \t]*\#[^\n]*)
 |(?P<num>0[xX][0-9a-fA-F]+[uUlL]*|\d+\.?\d*(?:[eE][+-]?\d+)?[uUlLfF]*)
 |(?P<id>[A-Za-z_]\w*)
 |(?P<op>->|\+\+|--|<<=|>>=|<<|>>|<=|>=|==|!=|&&|\|\||[-+*/%&|^]=|[{}()\[\];,.<>=!~?:+\-*/%&|^])
''', re.X | re.S | re.M)


def tokenize(src):
    """Return list of (kind, text, line). Includes comments and preprocessor lines."""
    starts = [0] + [m.end() for m in re.finditer(r"\n", src)]
    toks = []
    for m in _TOKEN_RE.finditer(src):
        kind = m.lastgroup
        toks.append((kind, m.group(), bisect.bisect_right(starts, m.start())))
    return toks


def code_tokens(src):
    return [t for t in tokenize(src) if t[0] not in ("comment", "pre")]


def comment_lines(src):
    n = 0
    for kind, text, _ in tokenize(src):
        if kind == "comment":
            n += text.count("\n") + 1
    return n


def functions(src):
    """Find function definitions. Returns list of dicts:
    name, start_line, end_line, length, cyclomatic, calls (set of identifiers called)."""
    toks = code_tokens(src)
    out, depth, i = [], 0, 0
    while i < len(toks):
        kind, text, line = toks[i]
        if text == "{" and depth == 0 and i > 0 and toks[i - 1][1] == ")":
            # walk back to the matching '('
            j, d = i - 1, 0
            while j >= 0:
                if toks[j][1] == ")":
                    d += 1
                elif toks[j][1] == "(":
                    d -= 1
                    if d == 0:
                        break
                j -= 1
            name_tok = toks[j - 1] if j > 0 else None
            if name_tok and name_tok[0] == "id" and name_tok[1] not in CONTROL:
                # find matching close brace
                k, d = i, 0
                while k < len(toks):
                    if toks[k][1] == "{":
                        d += 1
                    elif toks[k][1] == "}":
                        d -= 1
                        if d == 0:
                            break
                    k += 1
                body = toks[i:k + 1]
                cc = 1 + sum(1 for t in body if t[1] in ("if", "for", "while", "case", "&&", "||", "?"))
                calls = {body[x][1] for x in range(len(body) - 1)
                         if body[x][0] == "id" and body[x + 1][1] == "(" and body[x][1] not in CONTROL}
                end_line = toks[min(k, len(toks) - 1)][2]
                out.append({"name": name_tok[1], "start_line": name_tok[2], "end_line": end_line,
                            "length": end_line - name_tok[2] + 1, "cyclomatic": cc, "calls": calls})
                i = k + 1
                continue
        if text == "{":
            depth += 1
        elif text == "}":
            depth = max(0, depth - 1)
        i += 1
    return out


def declared_identifiers(src):
    toks = code_tokens(src)
    types = {"int", "long", "short", "char", "float", "double", "unsigned", "signed",
             "size_t", "void", "_Bool"}
    names = []
    for i, (kind, text, _) in enumerate(toks[:-1]):
        if text in types:
            j = i + 1
            while j < len(toks) and (toks[j][1] in types or toks[j][1] == "*"):
                j += 1
            if j < len(toks) and toks[j][0] == "id" and toks[j][1] not in KEYWORDS:
                nxt = toks[j + 1][1] if j + 1 < len(toks) else ""
                if nxt != "(":
                    names.append(toks[j][1])
    return names


def normalized_tokens(src):
    """Token stream for similarity: identifiers/numbers/strings collapsed."""
    out = []
    for kind, text, _ in code_tokens(src):
        if kind == "id":
            out.append(text if text in KEYWORDS else "ID")
        elif kind == "num":
            out.append("NUM")
        elif kind in ("str", "chr"):
            out.append("STR")
        else:
            out.append(text)
    return out
