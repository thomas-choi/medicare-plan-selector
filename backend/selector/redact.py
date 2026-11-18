"""PHI redactor for feedback free text (DESIGN §7).

Removes: drug names (a built-in lexicon of common Medicare drugs, common generic-name stems, and the user's own
drug list when we have it), names after "Dr."/"Doctor", emails, phone numbers, NPI-like and other long numbers
(Medicare/SSN-like ids), ZIP codes, and dates (birth dates and others). It errs on the side of over-redacting.
It is a best effort, not a guarantee, which is why raw text is kept only on explicit opt-in (encrypted).
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# Common Part D drugs (generic and brand). Lower case; matched as whole words.
_LEXICON_TEXT = """
    abilify acetaminophen albuterol alendronate allopurinol alprazolam amiodarone amlodipine amoxicillin
    anastrozole apixaban aricept aripiprazole atenolol atorvastatin azithromycin baclofen basaglar benazepril
    biktarvy brilinta budesonide bumetanide bupropion buspirone carbidopa carvedilol cefdinir celecoxib
    cephalexin cetirizine ciprofloxacin citalopram clonazepam clonidine clopidogrel cozaar crestor
    cyclobenzaprine dapagliflozin diclofenac digoxin diltiazem donepezil doxycycline dulaglutide duloxetine
    eliquis empagliflozin enalapril entresto escitalopram estradiol eszopiclone ezetimibe famotidine farxiga
    fenofibrate finasteride fluoxetine fluticasone furosemide gabapentin glimepiride glipizide glyburide humalog
    humira hydralazine hydrochlorothiazide hydrocodone hydroxychloroquine ibrance ibuprofen imbruvica insulin
    invokana isosorbide jardiance januvia ketoconazole lamotrigine lantus lasix levemir levetiracetam
    levofloxacin levothyroxine linagliptin linzess lipitor lisinopril lithium loratadine lorazepam losartan
    lovastatin lyrica meloxicam memantine metformin methimazole methocarbamol methotrexate methylphenidate
    methylprednisolone metoprolol metronidazole mirtazapine montelukast morphine mounjaro naproxen nexium
    nifedipine nitrofurantoin nitroglycerin norco novolog olanzapine olmesartan omeprazole ondansetron
    oxybutynin oxycodone ozempic pantoprazole paroxetine plavix pioglitazone pravastatin prednisone pregabalin
    premarin prilosec promethazine propranolol quetiapine ramipril ranolazine revlimid rivaroxaban rosuvastatin
    semaglutide seroquel sertraline sildenafil simvastatin sitagliptin spironolactone symbicort synthroid
    tamsulosin telmisartan temazepam terazosin tirzepatide topiramate torsemide tramadol trazodone trelegy
    triamcinolone trulicity valacyclovir valsartan venlafaxine verapamil victoza warfarin xarelto xtandi zetia
    zoloft zolpidem
"""
LEXICON = frozenset(_LEXICON_TEXT.split())
# Generic-name stems (statins, ACE inhibitors, ARBs, beta blockers, gliptins, GLP-1s, biologics, ...).
_STEMS = (
    r"\b\w{3,}(?:statin|pril|sartan|olol|gliptin|glutide|gliflozin|tide|mab|nib|azole|prazole|dipine|formin"
    r"|cycline|floxacin|vir|parin|xaban|lukast|tadine|oxetine|triptan|semide)\b"
)

_MONTH_DATE = (
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+"
    r"\d{1,2}(?:st|nd|rd|th)?,?\s+(?:19|20)\d{2}\b"
)
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[email]"),
    (re.compile(r"\b(?i:dr|doctor|dra)\.?\s+(?:[A-Z][\w'-]*\.?\s*){1,3}"), "Dr. [name] "),
    (re.compile(r"\b(?i:dr|doctor)\.?\s+(?!\[)[a-z][\w'-]*"), "Dr. [name]"),
    (re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"), "[date]"),
    (re.compile(r"\b(?:19|20)\d{2}-\d{1,2}-\d{1,2}\b"), "[date]"),
    (
        re.compile(
            r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+(?:19|20)\d{2}\b",
            re.I,
        ),
        "[date]",
    ),
    (re.compile(r"\b[1-9][A-Z][A-Z0-9]\d-?[A-Z][A-Z0-9]\d-?[A-Z]{2}\d{2}\b", re.I), "[id]"),  # Medicare MBI
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[id]"),  # SSN
    (re.compile(r"(?:\+?1[\s.-]?)?\(?\b\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b"), "[phone]"),
    (re.compile(r"\b\d{10}\b"), "[number]"),  # NPI-like
    (re.compile(r"\b\d{6,}\b"), "[number]"),
    (re.compile(r"\b\d{5}(?:-\d{4})?\b"), "[zip]"),
]
_STEM_RE = re.compile(_STEMS, re.I)


def redact(text: str, extra_terms: Iterable[str] = ()) -> str:
    out = text
    for pat, repl in _PATTERNS:
        out = pat.sub(repl, out)
    terms = sorted({t.strip().lower() for t in extra_terms if len(t.strip()) >= 3}, key=len, reverse=True)
    for t in terms:
        out = re.sub(rf"\b{re.escape(t)}\b", "[drug]", out, flags=re.I)
    out = re.sub(
        r"\b[a-z][a-z-]+\b", lambda m: "[drug]" if m.group(0).lower() in LEXICON else m.group(0), out, flags=re.I
    )
    out = _STEM_RE.sub("[drug]", out)
    return out.strip()
