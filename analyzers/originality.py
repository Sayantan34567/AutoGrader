"""Originality: flags suspected copying from other students, online sources or an LLM.

MOSS-style winnowing over normalized token k-grams (identifiers, numbers and strings collapsed, so
renaming variables or editing comments does not hide a copy). Compared against:
  - every other .c file in the corpus folders (other students; the instructor can also drop
    solutions found online there);
  - solutions the local LLM (Ollama) writes for the same problem (a few seeds, cached), to flag
    possible LLM output.
A flag is a lead for a human, never proof. On very short problems every correct solution looks alike.
"""
import hashlib
import re

import cparse
from llm import extract_c_code

NEEDS_EXECUTION = False
PARAMS = {
    "corpus_dirs": {"type": list, "items": str, "default": ["submissions/"]},
    "flag_threshold": {"type": float, "default": 0.85, "min": 0, "max": 1},
    "min_tokens": {"type": int, "default": 30, "min": 1},
    "k": {"type": int, "default": 5, "min": 2, "max": 20},
    "llm_reference_solutions": {"type": int, "default": 0, "min": 0, "max": 10},
    "llm_flag_threshold": {"type": float, "default": 0.9, "min": 0, "max": 1},
    "llm_match_penalty": {"type": float, "default": 0.0, "min": 0, "max": 1},
}

LLM_STYLE = [
    (r"//\s*(function to|helper function)", "'Function to ...' comment"),
    (r"//\s*(example usage|test the function)", "'Example usage' comment"),
    (r"printf\(\s*\"(Enter|Please enter)", "interactive prompt although input is piped"),
    (r"/\*\*[\s\S]*?@param", "Doxygen @param block"),
    (r"//\s*(return|step \d|read the|calculate the|print the)", "narrating comments"),
]
GEN_SYSTEM = "You are a C programmer. Reply with ONE complete C program in a ```c code block and nothing else."


def fingerprints(src, k=5, w=4):
    toks = cparse.normalized_tokens(src)
    if len(toks) < k:
        return set(), len(toks)
    grams = [hashlib.md5(" ".join(toks[i:i + k]).encode()).hexdigest()[:8]
             for i in range(len(toks) - k + 1)]
    if len(grams) <= w:
        return set(grams), len(toks)
    return {min(grams[i:i + w]) for i in range(len(grams) - w + 1)}, len(toks)


def similarity(a, b):
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0  # containment of the smaller set


def llm_solutions(ctx, n):
    """Programs the LLM writes for this problem: seeds 1..n, temperature 0.8, cached."""
    if n <= 0:
        return [], "disabled"
    if not ctx.llm.available():
        return [], "skipped: " + ctx.llm.status()[1]
    out = []
    for seed in range(1, n + 1):
        res = ctx.llm.chat(GEN_SYSTEM, f"Write a C program for this task:\n{ctx.statement}",
                           json_mode=False, temperature=0.8, seed=seed)
        if res["ok"]:
            out.append((f"llm:seed{seed}", extract_c_code(res["content"])))
    return out, "ok" if out else "skipped: the model returned nothing"


def analyze(ctx, params):
    k, thr = params["k"], params["flag_threshold"]
    mine, ntok = fingerprints(ctx.source, k)
    sims, ignored = [], []
    seen_files = set()
    for d in params["corpus_dirs"]:
        folder = ctx.resolve(d)
        if not folder.exists():
            continue
        for f in sorted(folder.rglob("*.c")):
            if f.resolve() == ctx.src.resolve() or f.resolve() in seen_files:
                continue
            seen_files.add(f.resolve())
            text = f.read_text(errors="replace")
            if f.name == ctx.src.name and text == ctx.source:
                ignored.append(f.name)  # same file resubmitted, not a copy
                continue
            label = str(f.relative_to(ctx.root)) if ctx.root in f.parents else f.name
            sims.append((round(similarity(mine, fingerprints(text, k)[0]), 4), label))
    sims.sort(key=lambda t: (-t[0], t[1]))
    top = sims[0] if sims else (0.0, None)

    llm_sims, llm_status = [], "disabled"
    if ntok >= params["min_tokens"]:
        sols, llm_status = llm_solutions(ctx, params["llm_reference_solutions"])
        llm_sims = sorted(((round(similarity(mine, fingerprints(code, k)[0]), 4), name)
                           for name, code in sols), key=lambda t: (-t[0], t[1]))
    ltop = llm_sims[0] if llm_sims else (0.0, None)
    signals = [label for pat, label in LLM_STYLE if re.search(pat, ctx.source, re.I)]
    ev = {"max_similarity": top[0], "most_similar_to": top[1], "threshold": thr, "tokens": ntok,
          "compared_files": len(sims), "ignored_identical_resubmission": ignored,
          "top_matches": sims[:3], "llm_style_signals": signals,
          "llm_solutions": {"status": llm_status, "max_similarity": ltop[0], "closest": ltop[1],
                            "threshold": params["llm_flag_threshold"], "compared": len(llm_sims)}}
    if ntok < params["min_tokens"]:
        return {"score": 1.0, "evidence": {**ev, "note": "too short to judge"},
                "feedback": f"Program too short ({ntok} tokens) for a meaningful similarity check."}
    flags, score = [], 1.0
    if top[0] >= thr:
        flags.append(
            f"suspected_copy: similarity {top[0]:.2f} with {top[1]} "
            "(human review required; no automatic penalty)"
        )
    if ltop[0] >= params["llm_flag_threshold"]:
        flags.append(f"possible_llm_generated: similarity {ltop[0]:.2f} with {ltop[1]} "
                     f"(weak evidence on short problems)")
        score = max(0.0, score - params["llm_match_penalty"])
    if len(signals) >= 3:
        flags.append("possible_llm_style: " + ", ".join(signals))
    fb = f"max similarity {top[0]:.2f}" + (" (FLAGGED for human review)" if top[0] >= thr else " (safe)")
    if llm_sims:
        fb += f"; closest LLM solution {ltop[0]:.2f}"
    return {"score": score, "evidence": ev, "feedback": fb, "flags": flags}
