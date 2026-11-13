"""
Institutional Paper Format Specification & Pre-configured Blueprints.
Enforces structural rigor across Rubric Parsing, Page Routing, and Scoring.
"""
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field
import re


class PaperSlot(BaseModel):
    slot_id: str = Field(..., description="Unique slot identifier, e.g. '1.a', '2.c', '3.a'")
    name: str = Field(..., description="Default descriptive slot name")
    part: str = Field(..., description="Examination Part, e.g. 'Part A', 'Part B', 'Part C'")
    max_marks: float = Field(..., description="Maximum marks for this slot")
    is_compulsory: bool = Field(True, description="Whether this slot is compulsory")
    choice_group: str = Field("", description="Choice group name, e.g. 'part_b_choice', 'part_c_choice'")
    choice_option: str = Field("", description="Option ID within choice group, e.g. '2c', '2d', 'Q3', 'Q4'")
    keywords: List[str] = Field(default_factory=list, description="Keywords and token patterns for matching")
    default_model_answer: str = Field("", description="Fallback expected answer description")
    default_mark_bands: str = Field("", description="Standard step marking criteria")


class PaperPartSpec(BaseModel):
    name: str = Field(..., description="Part Name, e.g. 'Part A'")
    max_marks: float = Field(..., description="Total marks maximum for this part")
    description: str = Field("", description="Part description and choice rules")


class PaperFormatSpec(BaseModel):
    format_id: str = Field(..., description="Unique format identifier, e.g. 'cie_50m_standard'")
    name: str = Field(..., description="Format display name")
    total_marks: float = Field(50.0, description="Total maximum exam marks")
    parts: List[PaperPartSpec] = Field(default_factory=list)
    slots: List[PaperSlot] = Field(default_factory=list)
    best_of_choice_enabled: bool = Field(True, description="Whether higher-scoring choice branch is selected")


# ---------------------------------------------------------------------------
# Pre-Configured Blueprint: Autonomous CIE Internal Assessment (50.0 Marks)
# ---------------------------------------------------------------------------
CIE_INTERNAL_50M_SPEC = PaperFormatSpec(
    format_id="cie_50m_standard",
    name="Autonomous College CIE Internal Assessment (50 Marks)",
    total_marks=50.0,
    parts=[
        PaperPartSpec(
            name="Part A",
            max_marks=10.0,
            description="100% Compulsory. 2 questions of 5 marks each (Q1.a and Q1.b).",
        ),
        PaperPartSpec(
            name="Part B",
            max_marks=20.0,
            description="Compulsory questions Q2.a (5M) and Q2.b (5M), plus internal choice between Q2.c (10M) OR Q2.d (10M).",
        ),
        PaperPartSpec(
            name="Part C",
            max_marks=20.0,
            description="Full Module Choice: EITHER Question 3 (3.a [10M] + 3.b [10M]) OR Question 4 (4.a [10M] + 4.b [10M]).",
        ),
    ],
    slots=[
        # Part A (10 Marks) - 100% Compulsory
        PaperSlot(
            slot_id="1.a",
            name="1.a Byte Addressability & Endianness",
            part="Part A",
            max_marks=5.0,
            is_compulsory=True,
            choice_group="",
            choice_option="1a",
            keywords=[
                "1.a", "1a", "(1a)", "1a)", "byte addressability", "byte addressable",
                "big endian", "little endian", "msb", "lsb", "byte ordering", "32-byte",
            ],
            default_model_answer="Explanation of byte addressability, Big-Endian (lower byte to MSB), Little-Endian (lower byte to LSB), with memory address mapping example.",
            default_mark_bands="2.5 marks for Byte Addressability concept; 2.5 marks for Big/Little Endian definitions and diagrams/examples.",
        ),
        PaperSlot(
            slot_id="1.b",
            name="1.b Basic Gates & Universal Gates",
            part="Part A",
            max_marks=5.0,
            is_compulsory=True,
            choice_group="",
            choice_option="1b",
            keywords=[
                "1.b", "1b", "(1b)", "1b)", "basic gates", "universal gates",
                "and gate", "or gate", "not gate", "nand gate", "nor gate", "truth table",
            ],
            default_model_answer="Definition, truth tables, and logic expressions for basic gates (AND, OR, NOT) and universal gates (NAND, NOR).",
            default_mark_bands="2.5 marks for Basic gates with truth tables; 2.5 marks for Universal gates (NAND, NOR) with definitions and truth tables.",
        ),

        # Part B (20 Marks) - Compulsory + Intra-Question Choice (2c OR 2d)
        PaperSlot(
            slot_id="2.a",
            name="2.a Addressing Modes & Effective Address Calculation",
            part="Part B",
            max_marks=5.0,
            is_compulsory=True,
            choice_group="",
            choice_option="2a",
            keywords=[
                "2.a", "2a", "(2a)", "2a)", "addressing mode", "effective address",
                "ea", "index addressing", "base with index", "offset", "r1", "r2", "r3", "r6", "r7", "3824", "765",
            ],
            default_model_answer="Identification of addressing modes and step-by-step effective address (EA) calculations for instructions.",
            default_mark_bands="1.5 marks for mode identification; 3.5 marks for correct step-by-step EA calculations.",
        ),
        PaperSlot(
            slot_id="2.b",
            name="2.b Boolean Expression to Canonical Minterm Form & Truth Table",
            part="Part B",
            max_marks=5.0,
            is_compulsory=True,
            choice_group="",
            choice_option="2b",
            keywords=[
                "2.b", "2b", "(2b)", "2b)", "minterm", "canonical", "canonical minterm",
                "truth table", "boolean expression", "f1 =", "sop", "minterms",
            ],
            default_model_answer="Algebraic expansion to canonical sum-of-minterms form and complete truth table.",
            default_mark_bands="2.5 marks for algebraic expansion to canonical minterms; 2.5 marks for complete truth table.",
        ),
        PaperSlot(
            slot_id="2.c",
            name="2.c Canonical Forms - SOP to POS Conversion",
            part="Part B",
            max_marks=10.0,
            is_compulsory=False,
            choice_group="part_b_choice",
            choice_option="2c",
            keywords=[
                "2.c", "2c", "(2c)", "2c)", "product of sums", "pos", "canonical pos",
                "sop to pos", "maxterms", "pi m", "product of maxterms",
            ],
            default_model_answer="Conversion of Boolean function from SOP minterms to POS maxterms representation with formal expansion.",
            default_mark_bands="5 marks for identifying maxterm indices; 5 marks for formal canonical POS algebraic expression.",
        ),
        PaperSlot(
            slot_id="2.d",
            name="2.d Stack Operations using Addressing Modes",
            part="Part B",
            max_marks=10.0,
            is_compulsory=False,
            choice_group="part_b_choice",
            choice_option="2d",
            keywords=[
                "2.d", "2d", "(2d)", "2d)", "stack operations", "stack", "push", "pop",
                "stack pointer", "sp", "r5", "#40", "removing top 10 items", "subroutine call",
            ],
            default_model_answer="Assembly instructions implementing stack push/pop operations, stack pointer manipulation, and parameter retrieval.",
            default_mark_bands="3 marks for register/stack setup; 4 marks for push/pop pointer adjustments (#40); 3 marks for retrieval and call sequence.",
        ),

        # Part C (20 Marks) - Full Question Choice: Either Q3 (3a + 3b) OR Q4 (4a + 4b)
        PaperSlot(
            slot_id="3.a",
            name="3.a Assembly Subroutine to Add N Numbers via Stack",
            part="Part C",
            max_marks=10.0,
            is_compulsory=False,
            choice_group="part_c_choice",
            choice_option="Q3",
            keywords=[
                "3.a", "3a", "(3a)", "3a)", "q3", "listadd", "add n numbers",
                "assembly subroutine", "assembly program", "parameter passed through stack",
                "load r2", "load r3", "call listadd", "store r5", "subroutine to add",
            ],
            default_model_answer="Complete assembly language program/subroutine defining parameter passing via stack, loop initialization, counter decrement, accumulator addition, and return.",
            default_mark_bands="3 marks for stack parameter setup and calling sequence; 4 marks for loop addition logic and register manipulation; 3 marks for result storage and return.",
        ),
        PaperSlot(
            slot_id="3.b",
            name="3.b K-Map Simplification & Logic Diagram",
            part="Part C",
            max_marks=10.0,
            is_compulsory=False,
            choice_group="part_c_choice",
            choice_option="Q3",
            keywords=[
                "3.b", "3b", "(3b)", "3b)", "k-map", "kmap", "karnaugh map",
                "logic diagram", "simplification", "f(x,y,z)", "sigma m", "grouping",
                "quad", "pair", "essential prime",
            ],
            default_model_answer="Accurate 3-variable/4-variable K-map grid plotting minterms, optimal groupings (quads/pairs), minimal SOP expression, and clean logic gate diagram sketch.",
            default_mark_bands="3 marks for correct K-map plot; 4 marks for prime implicant groupings and simplified expression; 3 marks for logic circuit schematic.",
        ),
        PaperSlot(
            slot_id="4.a",
            name="4.a Subroutine Linkage Mechanism & Stack Frames",
            part="Part C",
            max_marks=10.0,
            is_compulsory=False,
            choice_group="part_c_choice",
            choice_option="Q4",
            keywords=[
                "4.a", "4a", "(4a)", "4a)", "q4", "subroutine linkage", "linkage mechanism",
                "stack frames", "stack frame", "return address", "link register", "activation record",
            ],
            default_model_answer="Explanation of subroutine call/return mechanisms, link register, stack frame organization, local variable allocation, and saved registers.",
            default_mark_bands="4 marks for call/return sequence and return address handling; 6 marks for stack frame layout diagram and activation record explanation.",
        ),
        PaperSlot(
            slot_id="4.b",
            name="4.b Processor Internal Organization & Fetch/Execute Cycles",
            part="Part C",
            max_marks=10.0,
            is_compulsory=False,
            choice_group="part_c_choice",
            choice_option="Q4",
            keywords=[
                "4.b", "4b", "(4b)", "4b)", "processor internal organization", "internal organization",
                "single bus", "multiple bus", "fetch cycle", "execute cycle", "instruction fetch",
                "alu", "pc", "ir", "mar", "mdr",
            ],
            default_model_answer="Single-bus/three-bus processor architecture diagram showing PC, IR, MAR, MDR, ALU, General Purpose Registers, and micro-operation step control sequences for fetch/execute.",
            default_mark_bands="5 marks for processor internal architecture diagram; 5 marks for step-by-step fetch and execute control sequences.",
        ),
    ],
)


def get_default_cie_spec() -> PaperFormatSpec:
    """Returns the standard Autonomous 50-mark CIE Paper Format Specification."""
    return CIE_INTERNAL_50M_SPEC


def match_slot_by_text(text: str, spec: Optional[PaperFormatSpec] = None) -> Optional[PaperSlot]:
    """Matches a text snippet or question title to the most appropriate PaperSlot."""
    spec = spec or CIE_INTERNAL_50M_SPEC
    t_lower = text.lower().strip()

    # 1. Exact slot ID match at the start (e.g. "3.a", "(3a)", "3a)")
    for slot in spec.slots:
        m = re.search(rf"(?:^|\b|\()({re.escape(slot.slot_id)}|{re.escape(slot.slot_id.replace('.', ''))})(?:\)|\.|\s|$)", t_lower)
        if m:
            return slot

    # 2. Score by keywords
    best_slot = None
    best_score = 0
    for slot in spec.slots:
        score = 0
        for kw in slot.keywords:
            if kw in t_lower:
                score += len(kw.split()) * 2
        if score > best_score and score >= 4:
            best_score = score
            best_slot = slot

    return best_slot

