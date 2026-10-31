"""AutoGrader web front end (Streamlit).

    streamlit run main.py            # then open http://localhost:8501

The page only collects input and shows output; all grading is done by coordinator.grade().
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import streamlit as st

import sandbox
from check_rules import RulesError, validate_rules, with_defaults  # noqa: F401
from coordinator import ROOT, grade
from llm import OllamaClient

st.set_page_config(page_title="AutoGrader", page_icon="🧪", layout="wide")


# ----------------------------------------------------------------------------- helpers
def read_rules_file(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as e:
        return f"// could not read {path}: {e}"


def ollama_status(rules_path, force=False):
    """Cached (ok, message) for the Ollama server named in the rules file."""
    key = f"ollama::{rules_path}"
    if force or key not in st.session_state:
        try:
            cfg = json.loads(read_rules_file(rules_path)).get("llm", {})
        except json.JSONDecodeError:
            cfg = {}
        st.session_state[key] = OllamaClient(cfg).status(refresh=True)
    return st.session_state[key]


def list_sources():
    files = []
    for folder in ("submissions", "samples"):
        files += sorted((ROOT / folder).glob("*.c"))
    return files


def save_upload(name, data):
    up = ROOT / "uploads"
    up.mkdir(exist_ok=True)
    path = up / Path(name).name  # strip any directory part
    path.write_bytes(data if isinstance(data, bytes) else data.encode())
    return path


def metric_rows(report):
    rows = []
    for m in report["metrics"]:
        pts = "n/a" if m["status"] in ("skipped_tool_missing", "analyzer_error") else \
            f"{m['contribution']:.1f} / {m['effective_weight'] * 100:.0f}"
        rows.append({"Metric": m["name"], "Weight %": round(m["weight"] * 100), "Points": pts,
                     "Status": m["status"], "Note": m["feedback"]})
    return rows


def show_report(report):
    c1, c2, c3 = st.columns(3)
    c1.metric("Overall grade", f"{report['grade']:.1f} / 100")
    c2.metric("Report", "PARTIAL" if report["partial"] else "complete")
    c3.metric("Local LLM", report["llm"]["model"] if report["llm"]["enabled"] else "not used")
    for fl in report["flags"]:
        st.warning(f"FLAG: {fl}")
    fp = report["first_pass"]
    st.caption(f"First pass: compiled={fp['compiled']}, smoke run={fp['smoke_status']}, "
               f"suspected_infinite_loop={fp['suspected_infinite_loop']}, "
               f"static sanity={fp['static_sanity']}")
    st.subheader("Metrics")
    st.dataframe(metric_rows(report), hide_index=True)
    st.bar_chart({m["name"]: m["contribution"] for m in report["metrics"]})

    if report["counterexamples"]:
        st.subheader("Where the program fails")
        shown = 0
        seen = set()
        for c in report["counterexamples"]:
            key = (c["category"].split(":")[0], c["why"][:40])
            if key in seen:
                continue
            seen.add(key)
            shown += 1
            with st.expander(f"[{c['category']}]  input {c['input'].strip()!r}", expanded=shown <= 2):
                st.write("**Input**");    st.code(repr(c["input"]), language="text")
                st.write("**Expected**"); st.code(repr(c["expected"]), language="text")
                st.write("**Got**");      st.code(repr(c["got"]), language="text")
                st.info(c["why"])
        st.caption(f"{len(report['counterexamples'])} failing input(s) found in total.")
    if report["suggestions"]:
        st.subheader("Suggestions")
        for s in report["suggestions"]:
            st.markdown(f"- {s}")
    if report.get("llm_summary"):
        st.subheader("Tutor summary")
        st.caption(f"Written by local model {report['llm_summary']['model']}; it does not affect the grade.")
        st.write(report["llm_summary"]["text"])

    with st.expander("Evidence per metric (JSON)"):
        for m in report["metrics"]:
            st.markdown(f"**{m['name']}** ({m['analyzer']})")
            st.json(m["evidence"], expanded=False)
    with st.expander("What the agent did (log)"):
        st.code("\n".join(report["agent_log"]), language="text")
    ul = report.get("usefulness_limitations")
    if ul:
        with st.expander("Usefulness and limitations of this evaluation"):
            st.markdown("**Useful for**")
            for u in ul["usefulness"]:
                st.markdown(f"- **{u['use_case']}**: {u['example']} *{u['benefit']}*")
            st.markdown("**Limitations**")
            for u in ul["limitations"]:
                st.markdown(f"- **{u['limitation']}**: {u['example']} *Mitigation: {u['mitigation']}*")

    stem = Path(report["submission"]).stem
    txt = (ROOT / "reports" / f"{stem}.txt")
    d1, d2 = st.columns(2)
    d1.download_button("Download JSON report", json.dumps(report, indent=2, default=str),
                       file_name=f"{stem}.json", mime="application/json")
    if txt.exists():
        d2.download_button("Download text report", txt.read_text(), file_name=f"{stem}.txt")


# ----------------------------------------------------------------------------- sidebar
st.sidebar.title("AutoGrader")
rules_name = st.sidebar.text_input("Rules file", "rules.json")
rules_path = ROOT / rules_name
use_llm = st.sidebar.checkbox("Use local LLM (Ollama)", value=True,
                              help="Readability review, extra edge cases, LLM-copy check, tutor summary.")
ok, msg = ollama_status(rules_path)
if st.sidebar.button("Re-check Ollama"):
    ok, msg = ollama_status(rules_path, force=True)
(st.sidebar.success if ok else st.sidebar.warning)(msg)
if not ok:
    st.sidebar.caption("Without Ollama the agent still grades; readability uses a heuristic and the "
                       "report is flagged.")
if not sandbox.SUPPORTED:
    st.sidebar.error(sandbox.UNSUPPORTED_MSG)

tab_grade, tab_batch, tab_rules, tab_about = st.tabs(["Grade one", "Batch", "Rules editor", "How it works"])

# ----------------------------------------------------------------------------- grade one
with tab_grade:
    st.header("Grade a submission")
    mode = st.radio("Source", ["Pick a file", "Upload a .c file", "Paste code"], horizontal=True)
    target = None
    if mode == "Pick a file":
        options = list_sources()
        choice = st.selectbox("File", options, format_func=lambda p: f"{p.parent.name}/{p.name}") if options else None
        target = choice
        if choice:
            with st.expander("Show source"):
                st.code(choice.read_text(), language="c")
    elif mode == "Upload a .c file":
        up = st.file_uploader("C source file", type=["c"])
        if up is not None:
            target = save_upload(up.name, up.getvalue())
    else:
        code = st.text_area("C code", height=260, value="#include <stdio.h>\n\nint main(void) {\n    return 0;\n}\n")
        if code.strip():
            target = save_upload("pasted.c", code)

    if st.button("Run grading", type="primary", disabled=target is None or not sandbox.SUPPORTED):
        log_box = st.empty()
        lines = []

        def on_event(e):
            lines.append(f"{e['stage']:<10} {e['message']}")
            log_box.code("\n".join(lines), language="text")

        try:
            with st.spinner("The agent is working..."):
                st.session_state["report"] = grade(target, rules_path, ROOT / "reports",
                                                   progress=on_event, use_llm=use_llm)
            log_box.empty()
        except RulesError as e:
            st.session_state.pop("report", None)
            st.error("The rules file is invalid:")
            for err in e.errors:
                st.write(f"- {err}")
        except Exception as e:  # show the problem instead of a stack trace page
            st.session_state.pop("report", None)
            st.error(f"{type(e).__name__}: {e}")
    if "report" in st.session_state:
        show_report(st.session_state["report"])

# ----------------------------------------------------------------------------- batch
with tab_batch:
    st.header("Grade many submissions")
    files = list_sources()
    picked = st.multiselect("Files", files, default=[f for f in files if f.parent.name == "submissions"],
                            format_func=lambda p: f"{p.parent.name}/{p.name}")
    if st.button("Grade all selected", disabled=not picked or not sandbox.SUPPORTED):
        bar, rows = st.progress(0.0), []
        try:
            for i, f in enumerate(picked, 1):
                r = grade(f, rules_path, ROOT / "reports", use_llm=use_llm)
                rows.append({"submission": f"{f.parent.name}/{f.name}", "grade": r["grade"],
                             "partial": r["partial"], "flags": "; ".join(r["flags"])})
                bar.progress(i / len(picked))
            st.session_state["batch"] = rows
        except RulesError as e:
            st.error("The rules file is invalid: " + "; ".join(e.errors))
    if st.session_state.get("batch"):
        st.dataframe(st.session_state["batch"], hide_index=True)
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(st.session_state["batch"][0]))
        w.writeheader()
        w.writerows(st.session_state["batch"])
        st.download_button("Download CSV", buf.getvalue(), file_name="grades.csv", mime="text/csv")
        st.caption("Full per-student reports are in the reports/ folder.")

# ----------------------------------------------------------------------------- rules editor
with tab_rules:
    st.header("Rules editor")
    st.caption("Metrics, weights, thresholds and LLM settings live in this JSON file. Weights must sum to 1.00.")
    key = f"rules_text::{rules_path}"
    if key not in st.session_state:
        st.session_state[key] = read_rules_file(rules_path)
    text = st.text_area("rules.json", key=key, height=480)
    b1, b2, _ = st.columns([1, 1, 4])
    check = b1.button("Validate")
    save = b2.button("Save")
    if check or save:
        try:
            parsed = json.loads(text)
            errors, warnings = validate_rules(parsed, ROOT)
        except json.JSONDecodeError as e:
            parsed, errors, warnings = None, [f"not valid JSON: {e}"], []
        for err in errors:
            st.error(err)
        for w_ in warnings:
            st.warning(w_)
        if not errors:
            total = sum(m["weight"] for m in parsed["metrics"] if m.get("enabled", True))
            st.success(f"Rules are valid. {len(parsed['metrics'])} metrics, weights sum to {total:.2f}.")
            if save:
                rules_path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")  # keep the instructor's formatting
                st.session_state.pop(f"ollama::{rules_path}", None)
                st.success(f"Saved to {rules_name}.")
        elif save:
            st.error("Not saved: fix the errors above first.")

# ----------------------------------------------------------------------------- about
with tab_about:
    st.header("How the agent works")
    st.markdown("""
1. **Rules check** - `check_rules.py` validates `rules.json` (weights sum to 1, known analyzers, parameter types).
2. **First pass (sanity check)** - compile with gcc, smoke-run the sample input under time and memory limits,
   check there is a `main`, a reader and a writer. A hang sets `suspected_infinite_loop` and execution-based
   analyzers are skipped (partial report).
3. **Dispatch** - one analyzer per metric: correctness, syntax, structure, modularity, logical (edge cases),
   complexity, memory safety, readability, originality.
4. **Collation** - weighted sum, counter-examples with expected output and explanation, suggestions,
   JSON report for machines and text report for students.

**Reproducibility:** fixed seeds, instruction counts instead of wall-clock time, LLM at temperature 0 with a
fixed seed and an on-disk cache, no timestamps in reports.
""")
    st.markdown("**Analyzers available:** " + ", ".join(sorted(__import__("analyzers").REGISTRY)))
