"""
Rubric Document Parser Service.
Extracts structured rubric components, marks, and model answers
from uploaded rubric files (PDF, DOCX, TXT) or raw strings.
Combines high-fidelity document text & table extraction with local SLM/VLM semantic structuring.
"""
import io
import os
import re
import json
import base64
from typing import Optional, List, Dict, Any
import httpx
from PIL import Image

from app.core.config import settings
from app.schemas.paper_format import (
    PaperFormatSpec,
    PaperSlot,
    CIE_INTERNAL_50M_SPEC,
    match_slot_by_text,
)


KNOWN_TITLES = [
    "Problem understanding and graph modeling",
    "Choice of algorithm",
    "Initialization of distance matrix",
    "Conversion of train data into graph edges",
    "Floyd-Warshall recurrence relation",
    "Pseudocode correctness",
    "Example execution/output",
    "Time complexity/space complexity",
    "Time complexity / space complexity",
    "Correctness",
    "Completeness",
    "Clarity & Diagrams",
    "Clarity",
    "Approach and Methodology",
    "Optimization and Constraints",
]

DEFAULT_FALLBACK_COMPONENTS = [
    {
        "name": "Correctness & Methodology",
        "marks": 5.0,
        "part": "Part A",
        "is_compulsory": True,
        "choice_group": "",
        "choice_option": "",
        "model_answer": "Complete and theoretically sound solution with valid reasoning and calculations.",
        "mark_bands": "Full marks for sound methodology and complete solution.",
    },
    {
        "name": "Clarity & Completeness",
        "marks": 5.0,
        "part": "Part A",
        "is_compulsory": True,
        "choice_group": "",
        "choice_option": "",
        "model_answer": "Clear presentation, accurate diagrams/pseudocode where applicable, and step-by-step breakdown.",
        "mark_bands": "Full marks for clear structure and comprehensive steps.",
    },
]


def repair_json_escapes(raw_str: str) -> str:
    """Fix invalid backslashes (e.g. LaTeX math \\min, \\sum, \\alpha) inside JSON strings."""
    return re.sub(r'\\(?!([\"\\/bfnrt]|u[0-9a-fA-F]{4}))', r'\\\\', raw_str)


def parse_json_safely(text: str) -> Optional[dict]:
    """Robustly extracts and parses a JSON object with schema key verification."""
    if not text:
        return None
    s = text.strip()

    # Clean markdown wrappers
    if s.startswith("```"):
        lines = s.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines).strip()

    def _try_load(chunk: str) -> Optional[dict]:
        for candidate in (chunk, repair_json_escapes(chunk)):
            try:
                d = json.loads(candidate, strict=False)
                if isinstance(d, dict) and any(k in d for k in ("components", "rubric_components")):
                    return d
            except Exception:
                pass
            for extra in ["}", "\n}", "\n}\n}", '"}]}', '"}']:
                try:
                    d = json.loads(candidate + extra, strict=False)
                    if isinstance(d, dict) and any(k in d for k in ("components", "rubric_components")):
                        return d
                except Exception:
                    pass
        return None

    d = _try_load(s)
    if d:
        return d

    matches = list(re.finditer(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', s))
    for m in reversed(matches):
        d = _try_load(m.group(0))
        if d:
            return d

    return None


def extract_docx_content(file_path: str) -> str:
    """
    Extracts paragraphs and structured tables from a Word document (.docx).
    Preserves table grids, question numbers, marks, and solution text in clean Markdown.
    """
    try:
        import docx
        doc = docx.Document(file_path)
        content_blocks = []

        # 1. Paragraphs (headings, preamble, instructions)
        for p in doc.paragraphs:
            txt = p.text.strip()
            if txt:
                content_blocks.append(txt)

        # 2. Structured Tables (e.g. Q.No | Scheme of Evaluation | Marks | CO)
        for tbl in doc.tables:
            table_rows = []
            for row in tbl.rows:
                row_cells = [" ".join(c.text.split()) for c in row.cells]
                if any(row_cells):
                    table_rows.append(row_cells)

            if table_rows:
                headers = table_rows[0]
                md_table = []
                md_table.append("| " + " | ".join(headers) + " |")
                md_table.append("| " + " | ".join(["---"] * len(headers)) + " |")
                for r in table_rows[1:]:
                    padded = list(r)
                    while len(padded) < len(headers):
                        padded.append("")
                    md_table.append("| " + " | ".join(padded[:len(headers)]) + " |")
                content_blocks.append("\n".join(md_table))

        return "\n\n".join(content_blocks)
    except Exception as exc:
        print(f"[RubricParser] Word extraction error: {exc}")
        return ""


def extract_scanned_pdf_text(file_path: str) -> str:
    """Render pages of a scanned PDF and extract text using the configured local OCR model."""
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(file_path)
        ollama_url = getattr(settings, "ollama_url", "http://127.0.0.1:11434")
        model_name = getattr(settings, "ocr_model", "qwen2.5vl:7b")
        extracted_lines = []

        # Process up to 12 pages
        for i in range(min(len(pdf), 12)):
            page = pdf[i]
            img = page.render(scale=1.5).to_pil().convert("RGB")
            img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

            payload = {
                "model": model_name,
                "prompt": "Transcribe all questions, sub-questions, question numbers, marks, and solution keys from this scheme page verbatim into clean Markdown tables and text.",
                "images": [b64],
                "stream": False,
                "options": {
                    "temperature": 0.0,
                    "repeat_penalty": 1.2,
                    "num_ctx": 16384,
                }
            }
            try:
                with httpx.Client(timeout=60.0) as client:
                    resp = client.post(f"{ollama_url}/api/generate", json=payload)
                    if resp.status_code == 200:
                        d = resp.json()
                        p_text = d.get("response", "").strip() or d.get("thinking", "").strip()
                        if p_text:
                            # Clean markdown fence wrappers
                            p_clean = re.sub(r'<think>.*?</think>', '', p_text, flags=re.DOTALL).strip()
                            if p_clean.startswith("```markdown"):
                                p_clean = p_clean[len("```markdown"):].strip()
                            if p_clean.startswith("```"):
                                p_clean = p_clean[len("```"):].strip()
                            if p_clean.endswith("```"):
                                p_clean = p_clean[:-3].strip()
                            extracted_lines.append(f"\n--- Page {i+1} ---\n{p_clean}")
            except Exception as e:
                print(f"[RubricParser] Page {i+1} OCR error: {e}")
                continue

        return "\n".join(extracted_lines)
    except Exception as exc:
        print(f"[RubricParser] Scanned PDF extraction failed: {exc}")
        return ""


def structure_rubric_with_slm(text: str) -> List[Dict[str, Any]]:
    """
    Uses local SLM (e.g. gemma4:e4b) to transform raw scheme text into structured JSON rubric components.
    Accurately extracts parts, compulsory vs choice groups, question names, marks, and model solutions.
    """
    if not text or len(text.strip()) < 20:
        return []

    ollama_url = getattr(settings, "ollama_url", "http://127.0.0.1:11434")
    model_name = getattr(settings, "eval_model", "gemma4:e4b")

    prompt = f"""You are an Expert Academic Exam Controller and Rubric Structuring System.
Convert the following examination scheme of evaluation / rubric document into a structured JSON list of question components matching institutional evaluation standards.

### SCHEME DOCUMENT TEXT:
{text[:20000]}

### TARGET INSTITUTIONAL SLOTS (EXACT 10 SLOTS - 50.0 MARKS TOTAL):
Map the extracted scheme content strictly into these 10 predefined examination slots:
- Slot 1.a: Fundamental Concepts (Part A, 5.0 Marks, Compulsory)
- Slot 1.b: Basic Principles / Truth Tables (Part A, 5.0 Marks, Compulsory)
- Slot 2.a: Analytical / Addressing Modes & EA (Part B, 5.0 Marks, Compulsory)
- Slot 2.b: Form Simplification / Canonical Minterms (Part B, 5.0 Marks, Compulsory)
- Slot 2.c: Canonical Forms - SOP to POS (Part B, 10.0 Marks, Choice Group: "part_b_choice", Option: "2c")
- Slot 2.d: Architecture / Stack Operations (Part B, 10.0 Marks, Choice Group: "part_b_choice", Option: "2d")
- Slot 3.a: Program / Subroutine via Stack (Part C, 10.0 Marks, Choice Group: "part_c_choice", Option: "Q3")
- Slot 3.b: Minimization / K-Map & Logic Circuit (Part C, 10.0 Marks, Choice Group: "part_c_choice", Option: "Q3")
- Slot 4.a: System Linkage / Stack Frames (Part C, 10.0 Marks, Choice Group: "part_c_choice", Option: "Q4")
- Slot 4.b: Hardware Organization / Bus & Cycles (Part C, 10.0 Marks, Choice Group: "part_c_choice", Option: "Q4")

### MANDATORY STRUCTURING DIRECTIVES:
1. IDENTIFY ALL MAIN QUESTIONS AND SUB-QUESTIONS:
   - Extract every discrete sub-question (e.g. "1.a", "1.b", "2.a", "2.b", "2.c", "2.d", "3.a", "3.b", "4.a", "4.b").
   - "name": Full descriptive title including question number and topic (e.g. "1.a Byte Addressability & Big/Little Endian").

2. SECTION / PART PARTITIONING:
   - Assign "part": "Part A", "Part B", "Part C".
   - Questions numbered 1 belong to Part A; 2 to Part B; 3 and 4 to Part C.

3. COMPULSORY VS CHOICE GROUPS:
   - Compulsory questions: "is_compulsory": true, "choice_group": "", "choice_option": ""
   - Sub-question alternative choices (e.g. 2c OR 2d):
     * "is_compulsory": false, "choice_group": "part_b_choice", "choice_option": "2c" (for 2c) and "2d" (for 2d)
   - Main question alternative choices (e.g. Q3 OR Q4, where Q3 has 3a+3b and Q4 has 4a+4b):
     * For 3a and 3b: "is_compulsory": false, "choice_group": "part_c_choice", "choice_option": "Q3"
     * For 4a and 4b: "is_compulsory": false, "choice_group": "part_c_choice", "choice_option": "Q4"

4. MARKS ALLOCATION:
   - "marks": Exact numeric maximum marks (5.0 for Part A and 2a/2b; 10.0 for 2c/2d and Part C).

5. MODEL ANSWER & CRITERIA:
   - "model_answer": Detailed expected technical solution, derivations, truth tables, formulas, equations, or code.
   - "mark_bands": Step-wise marking criteria (e.g. "2 marks for truth table, 4 marks for K-map, 4 marks for logic diagram").

Return ONLY a valid JSON object matching this schema:
{{
  "components": [
    {{
      "name": "1.a Byte Addressability & Big/Little Endian",
      "part": "Part A",
      "marks": 5.0,
      "is_compulsory": true,
      "choice_group": "",
      "choice_option": "",
      "model_answer": "Complete expected solution from the scheme",
      "mark_bands": "Marking breakdown criteria"
    }}
  ]
}}
"""

    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.0,
            "num_predict": 4096,
            "num_ctx": 24576,
        }
    }

    try:
        with httpx.Client(timeout=90.0) as client:
            resp = client.post(f"{ollama_url}/api/generate", json=payload)
            if resp.status_code == 200:
                raw_res = resp.json().get("response", "").strip()
                parsed = parse_json_safely(raw_res)
                if parsed and "components" in parsed and isinstance(parsed["components"], list):
                    valid_comps = []
                    for c in parsed["components"]:
                        if isinstance(c, dict) and c.get("name"):
                            valid_comps.append({
                                "name": str(c.get("name", "")).strip(),
                                "part": str(c.get("part", "Part A")).strip(),
                                "marks": float(c.get("marks", 5.0)),
                                "is_compulsory": bool(c.get("is_compulsory", True)),
                                "choice_group": str(c.get("choice_group", "") or "").strip(),
                                "choice_option": str(c.get("choice_option", "") or "").strip(),
                                "model_answer": str(c.get("model_answer", "") or "").strip(),
                                "mark_bands": str(c.get("mark_bands", "") or "").strip(),
                            })
                    if valid_comps:
                        print(f"[RubricParser] SLM successfully structured {len(valid_comps)} components.")
                        return valid_comps
    except Exception as exc:
        print(f"[RubricParser] SLM structuring exception: {exc}")

    return []


def parse_rubric_text(text: str) -> list[dict]:
    """Fallback rule-based parser: parses raw text from a rubric file into structured components."""
    if not text or not text.strip():
        return []

    raw_lines = [l.strip() for l in text.replace("\r", "").split("\n") if l.strip()]
    merged = []

    has_numbered = any(re.match(r"^\d+[\.\)]", l) for l in raw_lines)

    if has_numbered:
        for l in raw_lines:
            if re.match(r"^\d+[\.\)]", l):
                merged.append(l)
            elif (
                merged
                and not l.lower().startswith("total")
                and not l.lower().startswith("rubric")
                and not l.lower().startswith("component")
            ):
                merged[-1] += " " + l
    else:
        idx = 1
        for l in raw_lines:
            if l.lower().startswith("total") or l.lower().startswith("rubric:"):
                continue
            clean_l = re.sub(r"^[\*\-•\d\.\)]+\s*", "", l).strip()
            if clean_l and len(clean_l) > 3:
                merged.append(f"{idx}. {clean_l}")
                idx += 1

    components = []
    for item in merged:
        m_num = re.match(r"^(\d+[\.\)])\s*(.*)$", item)
        if not m_num:
            continue
        num_str, rest = m_num.groups()
        m_marks = re.search(r"(\d+(?:\.\d+)?)\s*(?:marks?|pts?)?\s*$", rest, re.IGNORECASE)
        marks = float(m_marks.group(1)) if m_marks else 1.0
        body = rest[:m_marks.start()].strip() if m_marks else rest

        title = body
        content = body

        matched_kt = False
        for kt in KNOWN_TITLES:
            pattern = re.escape(kt).replace(r"\ ", r"\s+").replace("-", ".")
            m_kt = re.search(pattern, body, re.IGNORECASE)
            if m_kt:
                title = body[:m_kt.end()].strip()
                content = body[m_kt.end():].strip()
                if not content:
                    content = title
                matched_kt = True
                break

        if not matched_kt:
            parts = re.split(r"[:\-–—]\s+", body, maxsplit=1)
            if len(parts) == 2:
                title = parts[0].strip()
                content = parts[1].strip()

        components.append({
            "name": f"{num_str} {title}" if not title.startswith(num_str) else title,
            "marks": marks,
            "part": "Part A",
            "is_compulsory": True,
            "choice_group": "",
            "choice_option": "",
            "model_answer": content,
            "mark_bands": f"{marks} marks for correct methodology and completeness.",
        })

    if not components and raw_lines:
        components.append({
            "name": "1. Assessment Criteria",
            "marks": 10.0,
            "part": "Part A",
            "is_compulsory": True,
            "choice_group": "",
            "choice_option": "",
            "model_answer": "\n".join(raw_lines[:10]),
            "mark_bands": "10 marks for meeting all assessment criteria.",
        })

    return components


def normalize_to_paper_format(
    components: List[Dict[str, Any]],
    raw_text: str = "",
    spec: Optional[PaperFormatSpec] = None,
) -> List[Dict[str, Any]]:
    """
    Guarantees strict compliance with the Institutional Paper Format Specification (50.0 Marks).
    Maps any extracted components or raw text into the exact 10 slots of the paper,
    preserving extracted model answers and criteria while enforcing correct marks and choice rules.
    """
    spec = spec or CIE_INTERNAL_50M_SPEC
    normalized = []

    # Map existing components by matched slot_id
    matched_slots: Dict[str, Dict[str, Any]] = {}
    for comp in components:
        comp_name = str(comp.get("name", ""))
        slot = match_slot_by_text(comp_name, spec)
        if not slot and comp.get("choice_option"):
            c_opt = str(comp.get("choice_option")).lower().strip()
            for s in spec.slots:
                if s.choice_option and s.choice_option.lower() == c_opt:
                    slot = s
                    break
        if slot and slot.slot_id not in matched_slots:
            matched_slots[slot.slot_id] = comp

    for slot in spec.slots:
        comp = matched_slots.get(slot.slot_id)
        if comp:
            name = comp.get("name", slot.name)
            # Ensure name has slot prefix
            if not name.startswith(slot.slot_id) and not re.match(rf"^{re.escape(slot.slot_id.replace('.', ''))}\b", name):
                name = f"{slot.slot_id} {name}"

            m_ans = str(comp.get("model_answer", "")).strip() or slot.default_model_answer
            m_bands = str(comp.get("mark_bands", "")).strip() or slot.default_mark_bands

            normalized.append({
                "name": name,
                "part": slot.part,
                "marks": slot.max_marks,
                "is_compulsory": slot.is_compulsory,
                "choice_group": slot.choice_group,
                "choice_option": slot.choice_option,
                "model_answer": m_ans,
                "mark_bands": m_bands,
            })
        else:
            # Slot wasn't explicitly extracted by SLM: scan raw_text for keywords
            content_from_text = ""
            if raw_text:
                for kw in slot.keywords:
                    pos = raw_text.lower().find(kw)
                    if pos != -1:
                        # Extract ~1200 chars surrounding the match
                        start = max(0, pos - 100)
                        end = min(len(raw_text), pos + 1200)
                        content_from_text = raw_text[start:end].strip()
                        break

            normalized.append({
                "name": slot.name,
                "part": slot.part,
                "marks": slot.max_marks,
                "is_compulsory": slot.is_compulsory,
                "choice_group": slot.choice_group,
                "choice_option": slot.choice_option,
                "model_answer": content_from_text or slot.default_model_answer,
                "mark_bands": slot.default_mark_bands,
            })

    return normalized


def parse_rubric_file(file_path: str) -> list[dict]:
    """
    Main Ingestion Entrypoint:
    Extracts text/tables from .docx, .pdf, or .txt files,
    then executes SLM semantic structuring into standardized RubricComponents.
    Falls back gracefully to regex heuristic parsing if SLM is unavailable.
    Guarantees strict compliance with the 50.0-mark Institutional CIE Blueprint.
    """
    if not os.path.exists(file_path):
        return []

    ext = os.path.splitext(file_path)[1].lower()
    text = ""

    if ext in (".docx", ".doc"):
        text = extract_docx_content(file_path)
    elif ext == ".pdf":
        try:
            import pypdfium2 as pdfium
            pdf = pdfium.PdfDocument(file_path)
            text = "\n".join(p.get_textpage().get_text_range() for p in pdf)
            if len(text.strip()) < 50:
                print(f"[RubricParser] PDF '{file_path}' has no digital text layer ({len(text.strip())} chars). Extracting via OCR...")
                text = extract_scanned_pdf_text(file_path)
        except Exception as e:
            print(f"[RubricParser] PDF extraction error: {e}")
            return normalize_to_paper_format([])
    else:
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except Exception as e:
            print(f"[RubricParser] Text read error: {e}")
            return normalize_to_paper_format([])

    if not text or not text.strip():
        print(f"[RubricParser] Warning: No text extracted from '{file_path}'. Enforcing default blueprint slots.")
        return normalize_to_paper_format([])

    # Primary Stage: SLM Semantic Structuring
    components = structure_rubric_with_slm(text)
    if not components:
        # Secondary Stage: Regex Fallback
        print(f"[RubricParser] SLM structuring produced empty result, attempting regex fallback on '{file_path}'...")
        components = parse_rubric_text(text)

    # Normalize strictly to Institutional CIE Paper Format Specification
    normalized = normalize_to_paper_format(components, raw_text=text)
    print(f"[RubricParser] Enforced Institutional Paper Format Blueprint: {len(normalized)} slots, {sum(c['marks'] for c in normalized)} gross marks.")
    return normalized
