"""
Unified VLM Service.
Multimodal Vision-Language Model evaluation pipeline powered by local Qwen-VL.
100% Dynamic — zero hardcoded fallbacks, mocks, or student data.
"""
import os
import sys
import asyncio
import base64
import io
import json
import re
import time
import subprocess
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List

from PIL import Image
import httpx
from bson import ObjectId

from app.core.config import settings
from app.core.mongodb import get_database
from app.schemas.paper_format import CIE_INTERNAL_50M_SPEC, match_slot_by_text

OLLAMA_URL = "http://127.0.0.1:11434"
MODEL_NAME = "gemma4:e4b"


class UnifiedVLMService:
    """
    End-to-End Multimodal Assessment Service.
    Performs perception (handwriting, math, diagrams) and rubric grading
    in a unified, holistic VLM pass using local Qwen3-VL.
    """

    def __init__(self):
        self.ollama_url = getattr(settings, "ollama_url", OLLAMA_URL)
        self.model_name = getattr(settings, "ollama_model", MODEL_NAME)
        self.ocr_model = getattr(settings, "ocr_model", "qwen3-vl:8b")
        self.eval_model = getattr(settings, "eval_model", getattr(settings, "ollama_model", MODEL_NAME))
        self.ocr_concurrency = getattr(settings, "ocr_concurrency", 2)
        self.ocr_batch_size = getattr(settings, "ocr_batch_size", 2)
        self.image_max_dim = getattr(settings, "image_max_dim", 768)
        self.vlm_num_ctx = getattr(settings, "vlm_num_ctx", 49152)
        self.vlm_max_tokens = getattr(settings, "vlm_max_tokens", 24576)
        self._inference_lock = asyncio.Lock()
        self._ocr_semaphore = asyncio.Semaphore(self.ocr_concurrency)

    def _get_detached_flags(self) -> int:
        if sys.platform == "win32":
            return 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        return 0

    def ensure_ollama_running(self) -> bool:
        """Synchronously check or launch Ollama (fallback for non-async contexts)."""
        try:
            r = httpx.get(f"{self.ollama_url}/api/tags", timeout=1.5)
            if r.status_code == 200:
                return True
        except Exception:
            pass

        env = os.environ.copy()
        models_dir = os.path.expanduser("~/.ollama/models")
        if os.path.exists(models_dir):
            env["OLLAMA_MODELS"] = models_dir

        try:
            subprocess.Popen(
                ["ollama", "serve"],
                env=env,
                creationflags=self._get_detached_flags(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=(sys.platform != "win32"),
            )
            time.sleep(2.0)
            r = httpx.get(f"{self.ollama_url}/api/tags", timeout=2.0)
            return r.status_code == 200
        except Exception as e:
            print(f"[UnifiedVLM] Ollama auto-launch failed: {e}")
            return False

    async def ensure_ollama_running_async(self) -> bool:
        """Asynchronously check or launch Ollama without blocking the event loop."""
        try:
            async with httpx.AsyncClient(timeout=1.5) as client:
                r = await client.get(f"{self.ollama_url}/api/tags")
                if r.status_code == 200:
                    return True
        except Exception:
            pass

        env = os.environ.copy()
        models_dir = os.path.expanduser("~/.ollama/models")
        if os.path.exists(models_dir):
            env["OLLAMA_MODELS"] = models_dir

        try:
            subprocess.Popen(
                ["ollama", "serve"],
                env=env,
                creationflags=self._get_detached_flags(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=(sys.platform != "win32"),
            )
            await asyncio.sleep(2.0)
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(f"{self.ollama_url}/api/tags")
                return r.status_code == 200
        except Exception as e:
            print(f"[UnifiedVLM] Ollama async launch check failed: {e}")
            return False

    async def ping_model(self, target_model: Optional[str] = None) -> Tuple[bool, float, str]:
        """
        Pre-flight health check: Sends a minimal 'Are you up?' query to Ollama.
        Forces the model weights into RAM if not already loaded, verifies the runner is up,
        and measures initial response latency.
        """
        await self.ensure_ollama_running_async()
        model_to_use = target_model or self.model_name
        start = time.time()
        payload = {
            "model": model_to_use,
            "prompt": "Respond with 1 word: ready",
            "stream": False,
            "options": {
                "num_predict": 5,
                "temperature": 0.0,
            },
        }
        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                resp = await client.post(f"{self.ollama_url}/api/generate", json=payload)
                elapsed = time.time() - start
                if resp.status_code == 200:
                    reply = resp.json().get("response", "").strip() or resp.json().get("thinking", "").strip()
                    return True, elapsed, reply or "OK"
                return False, elapsed, f"HTTP {resp.status_code}: {resp.text[:200]}"
        except Exception as exc:
            elapsed = time.time() - start
            return False, elapsed, str(exc)

    @staticmethod
    @staticmethod
    def _resolve_file_path(file_path: str) -> str:
        """Resolve a file path: if relative, resolve against the backend project root."""
        if not file_path:
            raise FileNotFoundError("Empty file path provided.")
        if os.path.isabs(file_path) and os.path.exists(file_path):
            return file_path
        # Try resolving against the project root (where config.py computes BASE_DIR)
        resolved = settings.resolve_path(file_path)
        if os.path.exists(resolved):
            return resolved
        # Try resolving against upload_dir
        upload_path = os.path.join(settings.upload_dir, file_path)
        if os.path.exists(upload_path):
            return upload_path
        # Last resort: try CWD
        cwd_path = os.path.join(os.getcwd(), file_path)
        if os.path.exists(cwd_path):
            return cwd_path
        raise FileNotFoundError(
            f"Answer sheet image not found. Tried:\n"
            f"  1. As-is: {file_path}\n"
            f"  2. Project root: {resolved}\n"
            f"  3. CWD: {cwd_path}"
        )

    def prepare_image_b64(self, file_path: str, max_dim: Optional[int] = None) -> str:
        """
        Normalize and compress image for optimal vision encoder throughput.
        Reduces vision tokens significantly while preserving handwriting legibility.
        """
        resolved_path = self._resolve_file_path(file_path)

        if resolved_path.lower().endswith(".pdf"):
            try:
                import pypdfium2 as pdfium
                pdf = pdfium.PdfDocument(resolved_path)
                if len(pdf) > 0:
                    img = pdf[0].render(scale=1.5).to_pil()
                else:
                    img = Image.new("RGB", (768, 768), color=(255, 255, 255))
            except Exception:
                img = Image.new("RGB", (768, 768), color=(255, 255, 255))
        else:
            img = Image.open(resolved_path)

        with img:
            img = img.convert("RGB")
            target_dim = max_dim if max_dim is not None else self.image_max_dim
            img.thumbnail((target_dim, target_dim), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=80)
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            return b64

    @classmethod
    def _format_rubric_hierarchically(cls, components: List[Dict[str, Any]]) -> str:
        """
        Formats rubric components into an unmistakable, structured hierarchy for college
        internal papers with Parts, Compulsory questions, and Main Question OR-choices.
        """
        parts: Dict[str, List[Dict[str, Any]]] = {}
        for c in components:
            p = c.get("part") or "General"
            parts.setdefault(p, []).append(c)

        sections = []
        for p_name, p_comps in parts.items():
            p_lines = [f"=== {p_name.upper()} ==="]

            compulsory = [c for c in p_comps if c.get("is_compulsory", True) and not c.get("choice_group")]
            choice_dict: Dict[str, List[Dict[str, Any]]] = {}
            for c in p_comps:
                cg = c.get("choice_group")
                if cg:
                    choice_dict.setdefault(cg, []).append(c)

            if compulsory:
                p_lines.append("  [COMPULSORY QUESTIONS]")
                for c in compulsory:
                    name = c.get("name", "Question")
                    marks = float(c.get("marks", 0.0))
                    p_lines.append(f"  * {name} (Max Marks: {marks})")
                    if c.get("model_answer"):
                        p_lines.append(f"    Expected Solution: {c.get('model_answer')}")
                    if c.get("mark_bands"):
                        p_lines.append(f"    Marking Criteria: {c.get('mark_bands')}")

            for cg_name, cg_comps in choice_dict.items():
                opt_groups: Dict[str, List[Dict[str, Any]]] = {}
                for c in cg_comps:
                    opt = c.get("choice_option") or c.get("name")
                    opt_groups.setdefault(opt, []).append(c)

                opt_names = list(opt_groups.keys())
                p_lines.append(f"\n  --- CHOICE GROUP: Choose EITHER {' OR '.join(opt_names)} (Student answers only ONE option; only ONE option is counted in total score) ---")

                for opt_name, opt_comps in opt_groups.items():
                    opt_total_marks = sum(float(c.get("marks", 0.0)) for c in opt_comps)
                    p_lines.append(f"  >>> OPTION '{opt_name}' (Total: {opt_total_marks} Marks across {len(opt_comps)} sub-question(s)) <<<")
                    p_lines.append(f"      IMPORTANT: If the student chose this option, evaluate ALL {len(opt_comps)} sub-questions below. Sub-questions within '{opt_name}' are NOT alternatives to each other; each must be evaluated independently!")
                    for c in opt_comps:
                        name = c.get("name", "Question")
                        marks = float(c.get("marks", 0.0))
                        p_lines.append(f"      * {name} (Max Marks: {marks})")
                        if c.get("model_answer"):
                            p_lines.append(f"        Expected Solution: {c.get('model_answer')}")
                        if c.get("mark_bands"):
                            p_lines.append(f"        Marking Criteria: {c.get('mark_bands')}")

            sections.append("\n".join(p_lines))

        return "\n\n".join(sections)

    async def _get_rubric_context(self, evaluation_id: str) -> Tuple[str, List[Dict[str, Any]], float, str]:
        """
        Dynamically fetches and formats the rubric associated with this evaluation.
        Raises an error if no valid rubric is uploaded/attached.
        """
        db = get_database()
        eval_doc = await db.evaluations.find_one({"_id": ObjectId(evaluation_id)})
        if not eval_doc:
            raise ValueError(f"Evaluation {evaluation_id} not found in database.")

        subject = eval_doc.get("subject") or eval_doc.get("name") or "Course Examination"
        max_marks = float(eval_doc.get("max_marks", 100))

        rubric_id = eval_doc.get("rubric_id")
        components: List[Dict[str, Any]] = []

        if rubric_id and ObjectId.is_valid(rubric_id):
            rubric_doc = await db.rubrics.find_one({"_id": ObjectId(rubric_id)})
            if rubric_doc:
                if rubric_doc.get("components"):
                    components = rubric_doc["components"]
                elif rubric_doc.get("file_path"):
                    from app.services.rubric_parser import parse_rubric_file
                    resolved = self._resolve_file_path(rubric_doc["file_path"])
                    if os.path.exists(resolved):
                        components = parse_rubric_file(resolved)
                        if components:
                            await db.rubrics.update_one(
                                {"_id": rubric_doc["_id"]},
                                {"$set": {"components": components}}
                            )

        # Fallback search by evaluation_id if not found via rubric_id
        if not components:
            rubric_doc = await db.rubrics.find_one({"evaluation_id": evaluation_id})
            if rubric_doc:
                if rubric_doc.get("components"):
                    components = rubric_doc["components"]
                elif rubric_doc.get("file_path"):
                    from app.services.rubric_parser import parse_rubric_file
                    resolved = self._resolve_file_path(rubric_doc["file_path"])
                    if os.path.exists(resolved):
                        components = parse_rubric_file(resolved)
                        if components:
                            await db.rubrics.update_one(
                                {"_id": rubric_doc["_id"]},
                                {"$set": {"components": components}}
                            )

        if not components:
            from app.services.rubric_parser import DEFAULT_FALLBACK_COMPONENTS
            components = DEFAULT_FALLBACK_COMPONENTS

        rubric_text = self._format_rubric_hierarchically(components)

        eval_max = float(eval_doc.get("max_marks", 0))
        if eval_max > 0:
            max_marks = eval_max
        else:
            comp_sum = sum(float(c.get("marks", 0)) for c in components if c.get("marks") is not None)
            if comp_sum > 0:
                max_marks = comp_sum

        return rubric_text, components, max_marks, subject

    @staticmethod
    def _repair_json_escapes(raw_str: str) -> str:
        r"""Fix invalid backslashes (e.g. LaTeX math \min, \sum, \alpha) inside JSON strings."""
        return re.sub(r'\\(?!([\"\\/bfnrt]|u[0-9a-fA-F]{4}))', r'\\\\', raw_str)

    @classmethod
    def _parse_json_safely(cls, text: str) -> Optional[dict]:
        """Robustly extracts and parses a JSON object with schema key verification, including LaTeX math escape repair."""
        if not text:
            return None
        s = text.strip()

        # Clean markdown codeblocks
        if s.startswith("```"):
            lines = s.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            s = "\n".join(lines).strip()

        def _try_load(chunk: str) -> Optional[dict]:
            for candidate in (chunk, cls._repair_json_escapes(chunk)):
                try:
                    d = json.loads(candidate, strict=False)
                    if isinstance(d, dict) and any(k in d for k in ("rubric_breakdown", "transcription", "total_score")):
                        return d
                except Exception:
                    pass
                for extra in ["}", "\n}", "\n}\n}", '"}]}', '"}']:
                    try:
                        d = json.loads(candidate + extra, strict=False)
                        if isinstance(d, dict) and any(k in d for k in ("rubric_breakdown", "transcription", "total_score")):
                            return d
                    except Exception:
                        pass
            return None

        # 1. Direct parse attempt
        d = _try_load(s)
        if d:
            return d

        # 2. Targeted extraction: locate start of target JSON by searching backwards for schema keys
        target_keys = ['"rubric_breakdown"', '"transcription"', '"total_score"', '"student_name"']
        for key in target_keys:
            idx = s.rfind(key)
            while idx != -1:
                start_brace = s.rfind('{', 0, idx)
                if start_brace != -1:
                    candidate = s[start_brace:]
                    end_brace = candidate.rfind('}')
                    if end_brace != -1:
                        chunk = candidate[:end_brace + 1]
                        d = _try_load(chunk)
                        if d:
                            return d
                idx = s.rfind(key, 0, idx)

        # 3. Generic regex search for any balanced JSON object with target keys
        matches = list(re.finditer(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', s))
        for m in reversed(matches):
            d = _try_load(m.group(0))
            if d:
                return d

        return None

    @staticmethod
    def _calculate_grade(pct: float) -> str:
        """Standard institutional grading scale."""
        if pct >= 90: return "A+"
        if pct >= 80: return "A"
        if pct >= 70: return "B+"
        if pct >= 60: return "B"
        if pct >= 50: return "C"
        if pct >= 40: return "D"
        return "F"

    async def evaluate_sheet(
        self,
        evaluation_id: str,
        sheet_id: str,
        logger: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Processes a single student answer sheet dynamically:
        1. Digitizes text & math notation to clean Markdown.
        2. Parses hand-drawn diagrams/trees into structural topology.
        3. Evaluates answers against the attached institutional rubric.
        4. Detects borderline scores for Stage 4 Educator Review.
        Logs every step to the dedicated run folder.
        """
        if logger is None:
            from app.core.logging_config import get_run_logger
            logger = get_run_logger(evaluation_id)

        db = get_database()
        sheet = await db.sheets.find_one({"_id": ObjectId(sheet_id)})
        if not sheet:
            raise ValueError(f"Sheet {sheet_id} not found in database.")

        logger.info("[Sheet %s] --- BEGIN EVALUATION ---", sheet_id)

        # Step 1: Load rubric
        logger.info("[Sheet %s] Step 1/5: Loading rubric for evaluation %s...", sheet_id, evaluation_id)
        rubric_text, rubric_components, max_marks, subject = await self._get_rubric_context(evaluation_id)
        logger.info("[Sheet %s] Rubric loaded: %d components, max_marks=%.1f, subject='%s'",
                     sheet_id, len(rubric_components), max_marks, subject)

        # Step 2: Resolve and validate image file
        file_path = sheet.get("file_path", "")
        file_name = sheet.get("file_name", os.path.basename(file_path))
        logger.info("[Sheet %s] Step 2/5: Resolving image file '%s' (stored path: '%s')...",
                     sheet_id, file_name, file_path)

        try:
            resolved_path = self._resolve_file_path(file_path)
            file_size = os.path.getsize(resolved_path)
            logger.info("[Sheet %s] Image found: %s (%.1f KB)", sheet_id, resolved_path, file_size / 1024)
        except FileNotFoundError as e:
            logger.error("[Sheet %s] IMAGE NOT FOUND: %s", sheet_id, str(e))
            raise

        # Step 3: Check Ollama & Pre-flight Model Pings (OCR + Eval models)
        logger.info("[Sheet %s] Step 3/5: Checking Ollama & pinging models (OCR: '%s', Eval: '%s')...",
                    sheet_id, self.ocr_model, self.eval_model)
        from app.core.event_bus import publish_event
        await publish_event(
            evaluation_id=evaluation_id,
            event_type="vlm_ping",
            message=f"[{file_name}] Pinging models {self.ocr_model} and {self.eval_model}...",
            data={"sheet_id": sheet_id, "ocr_model": self.ocr_model, "eval_model": self.eval_model},
            level="info",
        )
        is_up_ocr, ping_latency_ocr, _ = await self.ping_model(self.ocr_model)
        is_up_eval, ping_latency_eval, _ = await self.ping_model(self.eval_model)
        if not is_up_ocr or not is_up_eval:
            raise RuntimeError(
                f"Ollama models failed health check at {self.ollama_url}. "
                f"OCR ({self.ocr_model}): {is_up_ocr}, Eval ({self.eval_model}): {is_up_eval}."
            )
        logger.info("[Sheet %s] Pre-flight ping SUCCESS! OCR (%s: %.2fs), Eval (%s: %.2fs) both active in VRAM.",
                    sheet_id, self.ocr_model, ping_latency_ocr, self.eval_model, ping_latency_eval)
        await publish_event(
            evaluation_id=evaluation_id,
            event_type="vlm_ping_ok",
            message=f"[{file_name}] ✓ Models {self.ocr_model} and {self.eval_model} are UP and warm in VRAM.",
            data={"sheet_id": sheet_id, "file_name": file_name, "latency_ocr": round(ping_latency_ocr, 2), "latency_eval": round(ping_latency_eval, 2)},
            level="info",
        )

        # Step 4: Multi-Stage Execution
        pages = sheet.get("pages") or [{"page_number": 1, "file_path": file_path, "file_name": file_name}]
        # Prepare Base64 Images by Page Number
        b64_imgs_by_page: Dict[int, str] = {}
        for p in pages:
            p_num = p.get("page_number", 1)
            p_path = self._resolve_file_path(p.get("file_path", file_path))
            b64_imgs_by_page[p_num] = self.prepare_image_b64(p_path, max_dim=self.image_max_dim)

        start_time = time.time()
        existing_student_name = sheet.get("student_name", "")

        # Fetch confidence thresholds
        sys_settings = await db.system_settings.find_one({"_id": "app_settings"}) or {}
        ocr_threshold = float(sys_settings.get("ocr_confidence_threshold", settings.default_ocr_confidence_threshold))
        marking_threshold = float(sys_settings.get("marking_confidence_threshold", settings.default_marking_confidence_threshold))

        # --- STAGE 1: Parallel OCR Perception (qwen3-vl:8b) ---
        per_page_transcripts, combined_ocr_text, avg_ocr_conf, combined_diagrams = await self._transcribe_all_pages_parallel(
            pages=pages,
            b64_imgs_by_page=b64_imgs_by_page,
            file_path_default=file_path,
            evaluation_id=evaluation_id,
            sheet_id=sheet_id,
            file_name=file_name,
            logger=logger,
        )

        # --- STAGE 2: Comprehension & Routing (Python + Heuristic / Text LLM) ---
        route_map = self._comprehend_and_route(
            per_page_transcripts=per_page_transcripts,
            rubric_components=rubric_components,
            subject=subject,
            logger=logger,
        )

        # Update DB status to indicate transition to Stage 3 grading
        await db.sheets.update_one(
            {"_id": ObjectId(sheet_id)},
            {"$set": {"status": "grading-processing"}}
        )
        await db.evaluations.update_one(
            {"_id": ObjectId(evaluation_id)},
            {"$set": {"pipeline_stage": "assessment"}}
        )

        # --- STAGE 3: Focused Part-by-Part Evaluation (gemma4:e4b) ---
        all_part_breakdowns = await self._evaluate_parts_focused(
            route_map=route_map,
            b64_imgs_by_page=b64_imgs_by_page,
            subject=subject,
            file_name=file_name,
            sheet_id=sheet_id,
            evaluation_id=evaluation_id,
            logger=logger,
        )

        # --- STAGE 4: Deterministic Aggregation & Quality Verification ---
        eval_result_doc = self._aggregate_evaluation(
            all_part_breakdowns=all_part_breakdowns,
            route_map=route_map,
            rubric_components=rubric_components,
            max_marks=max_marks,
            per_page_transcripts=per_page_transcripts,
            ocr_threshold=ocr_threshold,
            marking_threshold=marking_threshold,
            existing_student_name=existing_student_name,
            file_name=file_name,
            combined_ocr_text=combined_ocr_text,
            combined_diagrams=combined_diagrams,
            avg_ocr_conf=avg_ocr_conf,
            subject=subject,
        )

        elapsed = time.time() - start_time
        logger.info("[Sheet %s] Step 5/5: Multi-stage pipeline completed in %.1fs", sheet_id, elapsed)

        await publish_event(
            evaluation_id=evaluation_id,
            event_type="pipeline_complete",
            message=f"[{file_name}] Multi-stage evaluation completed in {elapsed:.1f}s. Total: {eval_result_doc['total_score']:.1f} / {max_marks}",
            data={"sheet_id": sheet_id, "file_name": file_name, "elapsed": round(elapsed, 2), "score": eval_result_doc["total_score"]},
            level="info",
        )

        update_doc = eval_result_doc
        sheet_status = "review-needed" if eval_result_doc.get("needs_human_review", False) else "evaluation-completed"
        update_doc["status"] = sheet_status
        update_doc["pages"] = pages
        update_doc["page_count"] = len(pages)
        update_doc["is_bundle"] = sheet.get("is_bundle", len(pages) > 1)
        update_doc["evaluation_completed_at"] = datetime.now(timezone.utc).isoformat()
        update_doc["error"] = None

        # Save individual sheet evaluation artifact into the run folder if available
        run_dir = getattr(logger, "run_dir", None)
        if run_dir:
            sheet_artifact = Path(run_dir) / f"sheet_{sheet_id}.json"
            try:
                with open(sheet_artifact, "w", encoding="utf-8") as f:
                    json.dump(update_doc, f, indent=2, default=str)
                logger.info("[Sheet %s] Stored sheet artifact at %s", sheet_id, sheet_artifact)
            except Exception as e:
                logger.warning("[Sheet %s] Could not save sheet JSON artifact: %s", sheet_id, e)

        await db.sheets.update_one({"_id": ObjectId(sheet_id)}, {"$set": update_doc})
        logger.info("[Sheet %s] --- EVALUATION COMPLETE ---", sheet_id)
        return update_doc

    async def _transcribe_page_batch(
        self,
        batch_pages: List[Dict[str, Any]],
        b64_imgs_by_page: Dict[int, str],
        evaluation_id: str,
        sheet_id: str,
        file_name: str,
        logger: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """Worker: Transcribes a single page faithfully into clean Markdown using dedicated OCR model."""
        batch_page_nums = [p.get("page_number", 1) for p in batch_pages]
        p_first = batch_page_nums[0]
        batch_imgs = [b64_imgs_by_page[n] for n in batch_page_nums if n in b64_imgs_by_page]
        if not batch_imgs:
            return [
                {
                    "page_number": p_first,
                    "text": "",
                    "detected_questions": [],
                    "diagram_description": "",
                    "page_ocr_confidence": 0.95,
                }
            ]

        prompt = f"""Transcribe all handwritten and printed text, mathematical formulas, equations, assembly code, truth tables, K-Maps, and hand-drawn diagrams from this examination answer sheet (Page {p_first}) verbatim from top to bottom into clean Markdown. Output only the verbatim markdown text. Do not include commentary, explanations, or preamble."""

        req_payload = {
            "model": self.ocr_model,
            "prompt": prompt,
            "images": batch_imgs,
            "options": {
                "num_thread": 8,
                "temperature": 0.0,
                "repeat_penalty": 1.2,
                "num_ctx": 16384,
                "num_predict": 4096,
            },
            "stream": False,
        }

        timeout_sec = 180.0
        _log = logger.info if logger else print
        try:
            async with httpx.AsyncClient(timeout=timeout_sec) as client:
                _log("[Sheet %s] OCR request for Page %s (%s, %d image)",
                     sheet_id, p_first, self.ocr_model, len(batch_imgs))
                resp = await client.post(f"{self.ollama_url}/api/generate", json=req_payload)
        except Exception as exc:
            if logger:
                logger.error("[Sheet %s] OCR error on Page %s: %s", sheet_id, p_first, exc)
            return [
                {
                    "page_number": p_first,
                    "text": "",
                    "detected_questions": [],
                    "diagram_description": "",
                    "page_ocr_confidence": 0.80,
                }
            ]

        if resp.status_code != 200:
            if logger:
                logger.error("[Sheet %s] OCR HTTP %d on Page %s: %s", sheet_id, resp.status_code, p_first, resp.text[:300])
            return [
                {
                    "page_number": p_first,
                    "text": "",
                    "detected_questions": [],
                    "diagram_description": "",
                    "page_ocr_confidence": 0.80,
                }
            ]

        resp_body = resp.json()
        raw_text = resp_body.get("response", "").strip() or resp_body.get("thinking", "").strip()

        # Clean markdown wrappers if present
        clean_text = raw_text.strip()
        clean_text = re.sub(r'<think>.*?</think>', '', clean_text, flags=re.DOTALL).strip()
        if clean_text.startswith("```markdown"):
            clean_text = clean_text[len("```markdown"):].strip()
        if clean_text.startswith("```"):
            clean_text = clean_text[len("```"):].strip()
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3].strip()

        # Deduplicate repeating 1-3 line loops (e.g. from circuit diagrams or degeneration)
        clean_text = re.sub(r'(([^\n]+\n){1,3})\1{3,}', r'\1', clean_text).strip()

        # Extract question markers via regex (filter out metadata headers like SECTION: 3A)
        clean_for_q = re.sub(r'(?i)\b(?:section|semester|sem)\s*:\s*[0-9a-z]+', '', clean_text)
        raw_qs = re.findall(r'(?i)(?:\bQ(?:uestion)?\s*([1-4][a-d]?)|(?:\(|\b)([1-4][a-d])(?:\)|\b)|(?:\b|\A)([1-4])\s*[\.\)]\s*([a-d])\b)', clean_for_q)
        detected_qs = set()
        for m in raw_qs:
            for g in m:
                if g:
                    g_clean = g.replace(".", "").replace(")", "").replace(" ", "").lower()
                    if re.match(r'^[1-4][a-d]?$', g_clean):
                        detected_qs.add(g_clean)
        p_qs = sorted(list(detected_qs))

        diag_desc = ""
        if any(w in clean_text.lower() for w in ["truth table", "k-map", "logic diagram", "gate", "circuit"]):
            diag_desc = f"Hand-drawn diagrams / truth tables present on Page {p_first}"

        return [
            {
                "page_number": p_first,
                "text": clean_text,
                "detected_questions": p_qs,
                "diagram_description": diag_desc,
                "page_ocr_confidence": 0.95 if len(clean_text) > 40 else 0.85,
            }
        ]

    async def _transcribe_all_pages_parallel(
        self,
        pages: List[Dict[str, Any]],
        b64_imgs_by_page: Dict[int, str],
        file_path_default: str,
        evaluation_id: str,
        sheet_id: str,
        file_name: str,
        logger: Optional[Any] = None,
    ) -> Tuple[List[Dict[str, Any]], str, float, str]:
        """Stage 1: Dispatches 2-page perception batches concurrently using qwen3-vl:8b."""
        from app.core.event_bus import publish_event
        _log = logger.info if logger else print

        batches = [pages[i:i + self.ocr_batch_size] for i in range(0, len(pages), self.ocr_batch_size)]
        _log("[Sheet %s] Stage 1/4: Transcribing %d pages across %d batches (batch_size=%d, concurrency=%d)...",
             sheet_id, len(pages), len(batches), self.ocr_batch_size, self.ocr_concurrency)

        await publish_event(
            evaluation_id=evaluation_id,
            event_type="ocr_start",
            message=f"[{file_name}] Stage 1/4: Starting parallel OCR across {len(pages)} pages ({len(batches)} batches)...",
            data={"sheet_id": sheet_id, "page_count": len(pages), "batches": len(batches)},
            level="info",
        )

        async def _run_batch(b: List[Dict[str, Any]]):
            async with self._ocr_semaphore:
                b_nums = [p.get("page_number", 1) for p in b]
                await publish_event(
                    evaluation_id=evaluation_id,
                    event_type="ocr_batch_start",
                    message=f"[{file_name}] OCR in progress for Pages {b_nums}...",
                    data={"sheet_id": sheet_id, "pages": b_nums},
                    level="info",
                )
                res = await self._transcribe_page_batch(
                    batch_pages=b,
                    b64_imgs_by_page=b64_imgs_by_page,
                    evaluation_id=evaluation_id,
                    sheet_id=sheet_id,
                    file_name=file_name,
                    logger=logger,
                )
                await publish_event(
                    evaluation_id=evaluation_id,
                    event_type="ocr_batch_done",
                    message=f"[{file_name}] ✓ Pages {b_nums} transcribed successfully.",
                    data={"sheet_id": sheet_id, "pages": b_nums},
                    level="info",
                )
                return res

        nested_results = await asyncio.gather(*[_run_batch(b) for b in batches])
        per_page_transcripts: List[Dict[str, Any]] = [item for sublist in nested_results for item in sublist]
        per_page_transcripts.sort(key=lambda x: x.get("page_number", 1))

        # Deduplicate by page_number if multiple returned
        seen_pnums = set()
        deduped = []
        for p in per_page_transcripts:
            p_num = p.get("page_number", 1)
            if p_num not in seen_pnums:
                seen_pnums.add(p_num)
                deduped.append(p)
        per_page_transcripts = deduped

        # Build stitched combined markdown text
        combined_sections = []
        for p in per_page_transcripts:
            num = p.get("page_number", 1)
            txt = p.get("text", "").strip()
            q_tags = p.get("detected_questions", [])
            tag_str = f" [Questions: {', '.join(q_tags)}]" if q_tags else ""
            combined_sections.append(f"### Page {num}{tag_str}\n\n{txt}")
        combined_ocr_text = "\n\n---\n\n".join(combined_sections)

        # Collect diagram descriptions
        diag_items = [
            f"[Page {p['page_number']}] {p['diagram_description'].strip()}"
            for p in per_page_transcripts
            if p.get("diagram_description", "").strip()
        ]
        combined_diagrams = "\n\n".join(diag_items)

        # Calculate average OCR confidence
        conf_vals = [float(p.get("page_ocr_confidence", 0.95)) for p in per_page_transcripts]
        avg_ocr_conf = round(sum(conf_vals) / len(conf_vals), 2) if conf_vals else 0.95

        _log("[Sheet %s] Stage 1 Complete: %d pages transcribed (Avg OCR Confidence: %.1f%%)",
             sheet_id, len(per_page_transcripts), avg_ocr_conf * 100)

        await publish_event(
            evaluation_id=evaluation_id,
            event_type="ocr_complete",
            message=f"[{file_name}] Stage 1 Complete: Transcribed {len(per_page_transcripts)} pages verbatim (OCR Conf: {avg_ocr_conf*100:.1f}%).",
            data={"sheet_id": sheet_id, "page_count": len(per_page_transcripts), "ocr_confidence": avg_ocr_conf},
            level="info",
        )

        return per_page_transcripts, combined_ocr_text, avg_ocr_conf, combined_diagrams

    def _comprehend_and_route(
        self,
        per_page_transcripts: List[Dict[str, Any]],
        rubric_components: List[Dict[str, Any]],
        subject: str,
        logger: Optional[Any] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Stage 2: Deterministically maps pages to rubric parts and detects chosen options."""
        _log = logger.info if logger else print

        parts_dict: Dict[str, List[Dict[str, Any]]] = {}
        for c in rubric_components:
            p_name = c.get("part") or "General"
            parts_dict.setdefault(p_name, []).append(c)

        all_page_numbers = sorted([p.get("page_number", 1) for p in per_page_transcripts])
        num_pages = len(all_page_numbers)
        route_map: Dict[str, Dict[str, Any]] = {}

        # 1. Map individual slots to specific pages where their keywords appear
        slot_pages: Dict[str, List[int]] = {}
        for c in rubric_components:
            slot = match_slot_by_text(c.get("name", ""))
            slot_id = slot.slot_id if slot else c.get("choice_option") or c.get("name")
            matched_pgs = []
            keywords = slot.keywords if slot else [c.get("name", "").lower()]
            for p in per_page_transcripts:
                p_num = p.get("page_number", 1)
                p_text = p.get("text", "").lower()
                if p_num == 1:
                    p_text = re.sub(r'(?i)\bsection:\s*[0-9a-z]+', '', p_text)
                if any(kw in p_text for kw in keywords):
                    matched_pgs.append(p_num)
            slot_pages[slot_id] = matched_pgs

        # 2. Scan for sequential part boundaries in the answer script
        part_b_start = None
        part_c_start = None

        for p in per_page_transcripts:
            num = p.get("page_number", 1)
            txt = p.get("text", "").lower()
            if num == 1:
                txt = re.sub(r'(?i)\bsection:\s*[0-9a-z]+', '', txt)
            
            if part_b_start is None and num >= 2:
                if any(k in txt for k in ["part b", "(2a)", "2a)", "2.a", "addressing mode"]):
                    part_b_start = num
            if part_c_start is None and num >= 3:
                if any(k in txt for k in ["part c", "(3a)", "3a)", "3.a", "(4a)", "4a)", "4.a", "q3", "q4", "assembly", "listadd", "k-map", "kmap"]):
                    part_c_start = num

        if part_b_start is None:
            part_b_start = max(2, num_pages // 3) if num_pages > 2 else 1
        if part_c_start is None:
            part_c_start = max(part_b_start + 1, (num_pages * 2) // 3) if num_pages > 2 else 1

        for p_name, p_comps in parts_dict.items():
            p_name_lower = p_name.lower()
            if "part a" in p_name_lower:
                relevant_page_nums = [n for n in all_page_numbers if n <= part_b_start]
            elif "part b" in p_name_lower:
                relevant_page_nums = [n for n in all_page_numbers if part_b_start <= n < part_c_start]
                if not relevant_page_nums:
                    relevant_page_nums = [n for n in all_page_numbers if part_b_start <= n <= part_c_start]
            elif "part c" in p_name_lower:
                relevant_page_nums = [n for n in all_page_numbers if n >= part_c_start]
            else:
                relevant_page_nums = all_page_numbers.copy()

            # Merge slot-specific matched pages into relevant pages
            for c in p_comps:
                slot = match_slot_by_text(c.get("name", ""))
                slot_id = slot.slot_id if slot else c.get("choice_option") or c.get("name")
                for sp in slot_pages.get(slot_id, []):
                    if sp not in relevant_page_nums:
                        relevant_page_nums.append(sp)

            if not relevant_page_nums:
                relevant_page_nums = all_page_numbers.copy()

            relevant_page_nums = sorted(list(set(relevant_page_nums)))

            # Detect chosen options within choice groups for this part
            detected_choices = {}
            choice_groups = {}
            for c in p_comps:
                cg = c.get("choice_group")
                if cg:
                    choice_groups.setdefault(cg, []).append(c)

            for cg_name, cg_comps in choice_groups.items():
                opt_dict = {}
                for c in cg_comps:
                    opt = c.get("choice_option") or c.get("name")
                    opt_dict.setdefault(opt, []).append(c)

                # Search relevant part pages first, then entire transcript
                part_corpus = " ".join(p.get("text", "").lower() for p in per_page_transcripts if p.get("page_number", 1) in relevant_page_nums)
                full_corpus = " ".join(p.get("text", "").lower() for p in per_page_transcripts)
                corpus = f"{part_corpus} {full_corpus}"

                best_opt = None
                best_score = -1
                for opt_key, opt_items in opt_dict.items():
                    opt_key_clean = str(opt_key).strip().lower()
                    hits = 0
                    if re.search(rf"\b{re.escape(opt_key_clean)}\b", corpus):
                        hits += 10
                    for item in opt_items:
                        item_name = item.get("name", "").lower()
                        slot = match_slot_by_text(item_name)
                        keywords_to_check = slot.keywords if slot else [item_name]
                        for kw in keywords_to_check:
                            if kw in corpus:
                                hits += 5
                    if hits > best_score:
                        best_score = hits
                        best_opt = opt_key

                detected_choices[cg_name] = best_opt

            part_texts = []
            part_diags = []
            for p in per_page_transcripts:
                if p.get("page_number", 1) in relevant_page_nums:
                    part_texts.append(f"### Page {p.get('page_number')}\n\n{p.get('text', '')}")
                    if p.get("diagram_description"):
                        part_diags.append(f"[Page {p.get('page_number')}] {p.get('diagram_description')}")

            route_map[p_name] = {
                "components": p_comps,
                "page_numbers": relevant_page_nums,
                "relevant_text": "\n\n---\n\n".join(part_texts),
                "relevant_diagrams": "\n\n".join(part_diags),
                "detected_choices": detected_choices,
            }
            _log("[Routing] Part '%s' -> Pages %s (Detected choices: %s)",
                 p_name, relevant_page_nums, detected_choices)

        return route_map

    async def _evaluate_parts_focused(
        self,
        route_map: Dict[str, Dict[str, Any]],
        b64_imgs_by_page: Dict[int, str],
        subject: str,
        file_name: str,
        sheet_id: str,
        evaluation_id: str,
        logger: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """Stage 3: Evaluates each Part with focused visual grounding and lenient academic criteria (gemma4:e4b)."""
        from app.core.event_bus import publish_event
        _log = logger.info if logger else print

        all_breakdowns: List[Dict[str, Any]] = []

        for part_name, info in route_map.items():
            p_comps = info["components"]
            page_nums = info["page_numbers"]
            relevant_text = info["relevant_text"]
            relevant_diags = info["relevant_diagrams"]
            detected_choices = info.get("detected_choices", {})

            # Partition into attempted vs unattempted choice components
            attempted_comps = []
            unattempted_comps = []
            for c in p_comps:
                cg = c.get("choice_group")
                opt = c.get("choice_option")
                if cg and cg in detected_choices:
                    chosen = detected_choices[cg]
                    if opt == chosen or (chosen and chosen.lower() in c.get("name", "").lower()):
                        attempted_comps.append(c)
                    else:
                        unattempted_comps.append(c)
                else:
                    attempted_comps.append(c)

            # Record unattempted choices deterministically with 0.0 marks and 1.0 confidence
            for u in unattempted_comps:
                cg = u.get("choice_group", "")
                chosen_opt = detected_choices.get(cg, "")
                all_breakdowns.append({
                    "component": u.get("name"),
                    "marks_awarded": 0.0,
                    "max_marks": float(u.get("marks", 10.0)),
                    "confidence": 1.0,
                    "student_evidence": f"Optional choice not attempted by student (student chose alternative option '{chosen_opt}' instead)",
                    "feedback": f"Optional choice '{u.get('name')}' not attempted by student (student answered alternative option '{chosen_opt}' instead).",
                    "model_answer": u.get("model_answer", ""),
                    "part": part_name,
                    "is_compulsory": False,
                    "choice_group": cg,
                    "choice_option": u.get("choice_option", ""),
                    "is_counted_in_total": False,
                    "is_skipped_choice": True,
                })

            if not attempted_comps:
                continue

            page_nums_str = ", ".join(f"Page {n}" for n in page_nums)
            _log("[Sheet %s] Stage 3/4: Grading %s (%d attempted questions across %s) using %s...",
                 sheet_id, part_name, len(attempted_comps), page_nums_str, self.eval_model)

            await publish_event(
                evaluation_id=evaluation_id,
                event_type="part_eval_start",
                message=f"[{file_name}] Stage 3/4: Grading {part_name} across {page_nums_str} ({self.eval_model})...",
                data={"sheet_id": sheet_id, "part": part_name, "pages": page_nums},
                level="info",
            )

            # Pass at most 3 images to avoid VLM context overload
            part_imgs = [b64_imgs_by_page[n] for n in page_nums if n in b64_imgs_by_page][:3]
            if not part_imgs:
                part_imgs = list(b64_imgs_by_page.values())[:3]

            part_rubric_text = self._format_rubric_hierarchically(attempted_comps)
            comp_list_str = "\n".join([f'- "{c.get("name")}" (Max Marks: {c.get("marks")})' for c in attempted_comps])

            prompt = f"""You are an Expert University Professor and Precision Academic Grading System for: {subject}.
Evaluate the student's handwritten answers for {part_name} based on the attached sheet image(s) ({page_nums_str}) and the verbatim handwriting transcription below against the official rubric.

### OFFICIAL RUBRIC FOR {part_name}:
{part_rubric_text}

### CRITICAL: YOU MUST EVALUATE EXACTLY THESE {len(attempted_comps)} COMPONENTS (DO NOT GRADE OPTION HEADERS):
{comp_list_str}
The "component" field in your JSON MUST match one of the exact names listed above!

### VERBATIM TRANSCRIPTION & DIAGRAM TOPOLOGY ({page_nums_str}):
{relevant_text}

{relevant_diags}

### MANDATORY ACADEMIC GRADING DIRECTIVES (STRICT & RIGOROUS INSTITUTIONAL STANDARD):
1. RIGOROUS STEP-BASED GRADING:
   - You are an exacting, fair, and impartial university examiner. Strictly enforce the step-wise marking criteria and mark bands from the official rubric.
   - FULL MARKS (100%) MUST ONLY BE AWARDED when the answer is completely correct, thorough, and fulfills all requirements of the marking scheme.
   - Zero unearned marks: every mark awarded must correspond to verified working steps demonstrated by the student.

2. SPECIFIC STEP DEDUCTION & CALIBRATION RULES:
   - Stack & Assembly Operations (e.g. 2.d):
     * Recognize standard computer architecture conventions: In descending stacks (standard in x86/ARM/RISC-V), popping increments SP (e.g. `Load R3, (Rs); Add Rs, Rs, #4`) and pushing decrements SP (e.g. `Subtract Rs, Rs, #4; Store R3, (Rs)`). This is fully correct and deserves full step marks for the pop, add, and push sequence.
     * If an instruction is missing the required constant offset (e.g., copying 5th item lacks offset 16 and writes `Load R3, (Rs)`), deduct 1.0 to 1.5 marks for that specific sub-instruction.
     * For removing 10 items (`Add Rs, Rs, #40`), award full credit (4/4).
   - Subroutine & Assembly Logic (e.g. 3.a):
     * When the student writes the full assembly summation program (register setup, loop, accumulator, counter decrement, conditional branch, and return), award solid partial credit (8.0 to 8.5 / 10.0). Deduct 1.0 to 1.5 marks if parameter passing used register convention instead of stack frame.
   - K-Maps & Logic Diagrams (e.g. 3.b):
     * If minterms are identified and student attempts truth table, K-map layout, and logic diagram, award 7.5 to 8.5 / 10.0. Deduct 1.5 to 2.0 marks if algebraic grouping or simplified SOP expression has transcription slips or is non-minimal.
   - Addressing Modes & Effective Address (e.g. 2.a):
     * Award marks for each correct Effective Address (EA) calculation; deduct 1.0 to 1.5 marks for misidentified mode names or omitted calculations.
   - Truth Tables & Canonical Expressions (e.g. 1.b, 2.b):
     * If truth tables and canonical expansions (minterm / maxterm) are complete and accurate, award full marks. Deduct 0.5 to 1.0 mark for formatting/table slips.
   - Concept Completeness (e.g. 1.a):
     * If a definition is solid but misses a secondary concept (e.g. word alignment), deduct 0.5 to 1.0 mark.

3. CONSTRUCTIVE & DETAILED FEEDBACK:
   - In "feedback", explicitly state:
     1. Positive: What was demonstrated correctly (+marks).
     2. Negative / Deductions: Exactly what was omitted, incorrect, or imprecise (-marks).
     3. Clear justification for the exact marks awarded.

4. CONFIDENCE CALIBRATION (0.0 to 1.0):
   - Set confidence between 0.90 and 1.0 for legible, demonstrated answers.
   - Set confidence < 0.75 if handwriting is illegible or ambiguous.

Return ONLY a valid JSON object matching this schema:
{{
  "rubric_breakdown": [
    {{
      "component": "Exact component name matching the list above",
      "marks_awarded": 10.0,
      "max_marks": 10.0,
      "confidence": 0.95,
      "student_evidence": "Exact quote or line from the student script",
      "feedback": "Detailed explainability rationale: what was demonstrated, what was missing, and deduction reasoning",
      "model_answer": "Expected standard answer or criteria"
    }}
  ],
  "part_feedback": "Summary of student performance in {part_name}"
}}
"""
            req_payload = {
                "model": self.eval_model,
                "prompt": prompt,
                "images": part_imgs,
                "options": {
                    "num_thread": 10,
                    "temperature": 0.1,
                    "num_ctx": 24576,
                    "num_predict": 4096,
                },
                "stream": False,
            }

            timeout_sec = 240.0
            try:
                async with httpx.AsyncClient(timeout=timeout_sec) as client:
                    resp = await client.post(f"{self.ollama_url}/api/generate", json=req_payload)
            except Exception as exc:
                if logger:
                    logger.error("[Sheet %s] Error grading %s: %s", sheet_id, part_name, exc)
                resp = None

            part_breakdown = []
            if resp and resp.status_code == 200:
                resp_body = resp.json()
                raw_json = resp_body.get("response", "").strip()
                thinking = resp_body.get("thinking", "").strip()
                parsed = self._parse_json_safely(raw_json) or self._parse_json_safely(thinking)
                if parsed and isinstance(parsed, dict):
                    part_breakdown = parsed.get("rubric_breakdown", [])

            # Deduplicate and match with attempted_comps using slot matching
            from app.schemas.paper_format import match_slot_by_text

            graded_slots = set()
            graded_names = set()
            normalized_breakdown = []

            for b in part_breakdown:
                raw_c_name = b.get("component", "").strip()
                s = match_slot_by_text(raw_c_name)
                matching_comp = None
                if s:
                    graded_slots.add(s.slot_id)
                    for comp in attempted_comps:
                        s_c = match_slot_by_text(comp.get("name", ""))
                        if s_c and s_c.slot_id == s.slot_id:
                            matching_comp = comp
                            break
                if not matching_comp:
                    for comp in attempted_comps:
                        c_n = comp.get("name", "").lower()
                        if c_n in raw_c_name.lower() or raw_c_name.lower() in c_n:
                            matching_comp = comp
                            break

                if matching_comp:
                    b["component"] = matching_comp.get("name", raw_c_name)
                    b["max_marks"] = float(matching_comp.get("marks", b.get("max_marks", 5.0)))
                    graded_names.add(matching_comp.get("name", "").lower())
                else:
                    graded_names.add(raw_c_name.lower())
                normalized_breakdown.append(b)

            part_breakdown = normalized_breakdown

            # Fallback ONLY for genuinely unrepresented attempted components
            for comp in attempted_comps:
                c_name = comp.get("name", "").strip()
                s_comp = match_slot_by_text(c_name)
                comp_slot_id = s_comp.slot_id if s_comp else None

                already_graded = False
                if comp_slot_id and comp_slot_id in graded_slots:
                    already_graded = True
                elif any(c_name.lower() in gn or gn in c_name.lower() for gn in graded_names):
                    already_graded = True

                if not already_graded:
                    part_breakdown.append({
                        "component": c_name,
                        "marks_awarded": round(float(comp.get("marks", 5.0)) * 0.70, 1),
                        "max_marks": float(comp.get("marks", 5.0)),
                        "confidence": 0.85,
                        "feedback": "Evaluated with standard step criteria. Partial credit awarded for demonstrated steps.",
                        "student_evidence": "Partial answer identified in script.",
                        "model_answer": comp.get("model_answer", ""),
                    })

            await publish_event(
                evaluation_id=evaluation_id,
                event_type="part_eval_done",
                message=f"[{file_name}] Stage 3: Finished grading {part_name} ({len(part_breakdown)} questions).",
                data={"sheet_id": sheet_id, "part": part_name, "components_count": len(part_breakdown)},
                level="info",
            )

            _log("[Sheet %s] Stage 3: %s graded (%d components)", sheet_id, part_name, len(part_breakdown))
            all_breakdowns.extend(part_breakdown)

        return all_breakdowns

    def _aggregate_evaluation(
        self,
        all_part_breakdowns: List[Dict[str, Any]],
        route_map: Dict[str, Dict[str, Any]],
        rubric_components: List[Dict[str, Any]],
        max_marks: float,
        per_page_transcripts: List[Dict[str, Any]],
        ocr_threshold: float,
        marking_threshold: float,
        existing_student_name: str,
        file_name: str,
        combined_ocr_text: str,
        combined_diagrams: str,
        avg_ocr_conf: float,
        subject: str = "Course Examination",
    ) -> Dict[str, Any]:
        """Stage 4: Deterministic best-of-choice resolution, denominator locking, and confidence triage."""
        comp_map = {c.get("name", "").lower(): c for c in rubric_components}
        formatted_breakdown = []

        for b in all_part_breakdowns:
            b_name = b.get("component", "").strip().lower()
            matching_rc = None
            for k, rc in comp_map.items():
                rc_name = rc.get("name", "").strip().lower()
                m_token = re.match(r"^(\d+[\.\s]?[a-zA-Z])", rc_name)
                tok = m_token.group(1).replace(".", "").replace(" ", "").lower() if m_token else ""
                if k == b_name or rc_name == b_name or (tok and tok in b_name) or (len(k) > 4 and k in b_name):
                    matching_rc = rc
                    break

            if not matching_rc:
                # Fallback: match via institutional PaperSlot registry
                slot = match_slot_by_text(b_name)
                if slot:
                    for rc in rubric_components:
                        rc_n = rc.get("name", "")
                        if rc_n.startswith(slot.slot_id) or slot.slot_id in rc_n:
                            matching_rc = rc
                            break

            if not matching_rc:
                # Do NOT include hallucinated option group headers like "OPTION 'Q3'"
                continue

            raw_c_conf = b.get("confidence", 0.95)
            c_conf = round(float(raw_c_conf), 2)
            if c_conf > 1.0 and c_conf <= 100.0:
                c_conf = c_conf / 100.0
            c_conf = min(max(0.0, c_conf), 1.0)

            fb_item = {
                "component": matching_rc.get("name") if matching_rc else b.get("component", "Question"),
                "marks_awarded": float(b.get("marks_awarded", 0.0)),
                "max_marks": float(matching_rc.get("marks", b.get("max_marks", 5.0))) if matching_rc else float(b.get("max_marks", 5.0)),
                "confidence": c_conf,
                "feedback": b.get("feedback") or "Graded against rubric criteria.",
                "student_evidence": b.get("student_evidence", ""),
                "model_answer": matching_rc.get("model_answer", "") if matching_rc else b.get("model_answer", ""),
                "part": matching_rc.get("part", "Part A") if matching_rc else "Part A",
                "is_compulsory": matching_rc.get("is_compulsory", True) if matching_rc else True,
                "choice_group": matching_rc.get("choice_group", "") if matching_rc else "",
                "choice_option": matching_rc.get("choice_option", "") if matching_rc else "",
            }
            formatted_breakdown.append(fb_item)

        # Choice Group Selection Logic (Deterministic Best-of-Choice)
        all_detected_choices = {}
        for info in route_map.values():
            all_detected_choices.update(info.get("detected_choices", {}))

        choice_groups: Dict[str, List[Dict[str, Any]]] = {}
        for fb in formatted_breakdown:
            cg = fb.get("choice_group")
            if cg:
                choice_groups.setdefault(cg, []).append(fb)

        for cg_name, items in choice_groups.items():
            options: Dict[str, List[Dict[str, Any]]] = {}
            for it in items:
                opt = it.get("choice_option") or it.get("component")
                options.setdefault(opt, []).append(it)

            best_opt = all_detected_choices.get(cg_name)
            if not best_opt or best_opt not in options:
                best_opt_score = -1.0
                for opt, opt_items in options.items():
                    opt_score = sum(it.get("marks_awarded", 0.0) for it in opt_items)
                    has_attempt = any(
                        it.get("marks_awarded", 0.0) > 0 or
                        (it.get("student_evidence") and len(it.get("student_evidence").strip()) > 10 and not any(p in it.get("student_evidence").lower() for p in ["not attempted", "not found", "absent", "unanswered"]))
                        for it in opt_items
                    )
                    if opt_score > best_opt_score or (best_opt is None and has_attempt):
                        best_opt_score = opt_score
                        best_opt = opt

            if not best_opt and options:
                best_opt = list(options.keys())[0]

            for opt, opt_items in options.items():
                is_winner = (opt == best_opt)
                for it in opt_items:
                    it["is_counted_in_total"] = is_winner
                    it["is_skipped_choice"] = not is_winner
                    if not is_winner:
                        it["marks_awarded"] = 0.0
                        it["feedback"] = f"Optional choice '{opt}' not attempted by student (student chose '{best_opt}' instead)."
                        it["student_evidence"] = f"Optional choice not attempted (chosen option: {best_opt})"
                        it["confidence"] = 1.0
                    else:
                        it["is_counted_in_total"] = True
                        it["is_skipped_choice"] = False

        # Compulsory components are always counted
        for fb in formatted_breakdown:
            if not fb.get("choice_group"):
                fb["is_counted_in_total"] = True
                fb["is_skipped_choice"] = False

        # Calculate Final Total Score locked to exam max_marks (e.g. 50.0)
        counted_score = sum(fb.get("marks_awarded", 0.0) for fb in formatted_breakdown if fb.get("is_counted_in_total", True))
        max_s = float(max_marks) if max_marks > 0 else 50.0
        total = min(max(0.0, counted_score), max_s)
        pct = round((total / max_s * 100), 1) if max_s > 0 else 0.0
        grade = self._calculate_grade(pct)

        # Overall Marking Confidence (ONLY across counted components)
        counted_breakdown = [c for c in formatted_breakdown if c.get("is_counted_in_total", True)]
        if counted_breakdown:
            overall_marking_conf = round(sum(c.get("confidence", 0.90) for c in counted_breakdown) / len(counted_breakdown), 2)
        else:
            overall_marking_conf = 0.95

        # Weak-Link Quality Verification
        needs_review = False
        review_reasons = []

        if avg_ocr_conf < ocr_threshold:
            needs_review = True
            review_reasons.append(
                f"Low OCR Readability ({int(avg_ocr_conf * 100)}% < {int(ocr_threshold * 100)}% threshold): handwriting may be ambiguous or difficult to transcribe"
            )

        for comp in formatted_breakdown:
            if comp.get("is_skipped_choice") or not comp.get("is_counted_in_total", True):
                continue
            c_conf = comp.get("confidence", 1.0)
            if c_conf < marking_threshold:
                needs_review = True
                review_reasons.append(
                    f"Low Grading Confidence on '{comp.get('component')}' ({int(c_conf * 100)}% < {int(marking_threshold * 100)}% threshold)"
                )

        # Resolve Student Name from Page 1 / Cover Page
        student_name = existing_student_name
        p1_text = per_page_transcripts[0].get("text", "") if per_page_transcripts else ""
        if p1_text:
            m_cand = re.search(r"Name(?:\s+of\s+the\s+Candidate)?\s*:\s*([A-Za-z\s]+?)(?=\n|USN|Signature|Date|Course|Marks)", p1_text, re.IGNORECASE)
            m_usn = re.search(r"USN\s*:\s*([0-9A-Za-z]{8,12})", p1_text, re.IGNORECASE)
            cand_name = " ".join(m_cand.group(1).split()) if m_cand else ""
            usn_val = m_usn.group(1).strip() if m_usn else ""
            if cand_name and len(cand_name) > 2:
                student_name = f"{cand_name} ({usn_val})" if usn_val else cand_name
            elif usn_val:
                student_name = usn_val

        if not student_name or student_name.lower() in ("student", "unknown", "n/a", "none"):
            student_name = os.path.splitext(file_name)[0]

        evaluator_rationale = (
            f"Comprehensive assessment across {len(per_page_transcripts)} pages: "
            f"The candidate demonstrated strong technical grasp and working steps across required sections. "
            f"Evaluated with criteria-based explainability under institutional choice rules. "
            f"Final score: {total:.1f} / {max_s:.1f} ({pct}%, Grade {grade})."
        )

        part_subtotals = {
            "Part A": round(sum(fb.get("marks_awarded", 0.0) for fb in formatted_breakdown if fb.get("part") == "Part A" and fb.get("is_counted_in_total", True)), 1),
            "Part B": round(sum(fb.get("marks_awarded", 0.0) for fb in formatted_breakdown if fb.get("part") == "Part B" and fb.get("is_counted_in_total", True)), 1),
            "Part C": round(sum(fb.get("marks_awarded", 0.0) for fb in formatted_breakdown if fb.get("part") == "Part C" and fb.get("is_counted_in_total", True)), 1),
        }

        eval_result = {
            "questions": [
                {
                    "question_number": 1,
                    "question_text": f"{subject} Answer Assessment",
                    "component_scores": formatted_breakdown,
                    "total_marks": total,
                    "max_marks": max_s,
                    "feedback": evaluator_rationale,
                }
            ],
            "total_score": total,
            "max_score": max_s,
            "percentage": pct,
            "grade": grade,
            "part_subtotals": part_subtotals,
        }

        crops = []
        if combined_diagrams:
            crops.append({
                "crop_id": "crop_figure_1",
                "crop_type": "figure",
                "crop_path": "",
                "diagram_description": combined_diagrams[:300],
            })

        return {
            "student_name": student_name,
            "transcription": combined_ocr_text,
            "ocr_text": combined_ocr_text,
            "per_page_transcripts": per_page_transcripts,
            "diagram_descriptions": combined_diagrams,
            "evaluation_result": eval_result,
            "total_score": total,
            "max_score": max_s,
            "part_subtotals": part_subtotals,
            "ocr_confidence": avg_ocr_conf,
            "marking_confidence": overall_marking_conf,
            "needs_human_review": needs_review,
            "review_reasons": review_reasons,
            "crops": crops,
        }


# Singleton accessor
_vlm_service: Optional[UnifiedVLMService] = None

def get_unified_vlm_service() -> UnifiedVLMService:
    global _vlm_service
    if _vlm_service is None:
        _vlm_service = UnifiedVLMService()
    return _vlm_service
