"""Shared medical vocabulary: conditions, medications and labs.

Each concept carries:
  * regex patterns that recognise it in free text (trial criteria, patient notes)
    and in Synthea FHIR display strings,
  * standard codes (SNOMED CT for conditions, RxNorm-style ingredient names for
    drugs, LOINC for labs) so Phase 2 can swap the regex lexicon for full UMLS
    normalisation without touching the evaluator.

The same vocabulary drives both sides of the match, which is what makes the
predicate evaluator deterministic and auditable.
"""

import re
from dataclasses import dataclass, field


@dataclass
class Concept:
    key: str
    label: str
    patterns: list[str]
    exclude: list[str] = field(default_factory=list)  # patterns that veto a match
    codes: list[str] = field(default_factory=list)
    acute: bool = False  # only a currently active episode counts unless "history of" is stated
    _rx: re.Pattern | None = None
    _ex: re.Pattern | None = None

    def __post_init__(self):
        self._rx = re.compile(r"\b(?:" + "|".join(self.patterns) + r")", re.I)
        self._ex = re.compile(r"\b(?:" + "|".join(self.exclude) + r")", re.I) if self.exclude else None

    def finditer(self, text: str):
        for m in self._rx.finditer(text):
            if self._ex:
                # veto if an exclusion pattern overlaps this match's neighbourhood
                lo, hi = max(0, m.start() - 15), min(len(text), m.end() + 15)
                if self._ex.search(text[lo:hi]):
                    continue
            yield m

    def matches(self, text: str) -> bool:
        return next(self.finditer(text), None) is not None


# --------------------------------------------------------------------------- conditions
CONDITIONS: list[Concept] = [
    Concept("type2_diabetes", "Type 2 diabetes mellitus",
            [r"type\s*(?:2|ii|two)\s*diabet\w*", r"t2dm", r"t2d\b", r"diabetes mellitus type\s*(?:2|ii)",
             r"non[- ]insulin[- ]dependent diabet\w*", r"niddm", r"adult[- ]onset diabet\w*",
             r"diabetes mellitus(?!\s*type\s*(?:1|i\b))", r"diabet(?:es|ic)(?! insipidus)"],
            exclude=[r"type\s*(?:1|i)\s*diabet", r"pre-?diabet", r"gestational", r"t1dm", r"insipidus"],
            codes=["SNOMED:44054006"]),
    Concept("type1_diabetes", "Type 1 diabetes mellitus",
            [r"type\s*(?:1|i|one)\s*diabet\w*", r"t1dm", r"t1d\b", r"insulin[- ]dependent diabet\w*", r"iddm",
             r"juvenile diabet\w*", r"diabetes mellitus type\s*(?:1|i)\b"],
            codes=["SNOMED:46635009"]),
    Concept("prediabetes", "Prediabetes", [r"pre-?diabet\w*", r"impaired (?:fasting )?glucose", r"impaired glucose tolerance"],
            codes=["SNOMED:714628002"]),
    Concept("hypertension", "Hypertension", [r"hypertensi\w*", r"high blood pressure", r"\bhtn\b"],
            exclude=[r"pulmonary (?:arterial )?hypertension", r"intracranial hypertension", r"portal hypertension",
                     r"ocular hypertension", r"pregnancy[- ]induced"],
            codes=["SNOMED:59621000"]),
    Concept("myocardial_infarction", "Myocardial infarction",
            [r"myocardial infarct\w*", r"heart attack", r"\bmi\b", r"\bstemi\b", r"\bnstemi\b", r"acute coronary syndrome", r"\bacs\b"],
            codes=["SNOMED:22298006"]),
    Concept("coronary_artery_disease", "Coronary artery disease",
            [r"coronary (?:artery|heart) disease", r"\bcad\b", r"\bchd\b", r"ischemic heart disease", r"ischaemic heart disease",
             r"angina(?: pectoris)?"],
            codes=["SNOMED:53741008"]),
    Concept("heart_failure", "Heart failure",
            [r"heart failure", r"cardiac failure", r"\bchf\b", r"\bhfref\b", r"\bhfpef\b", r"congestive heart"],
            codes=["SNOMED:84114007"]),
    Concept("atrial_fibrillation", "Atrial fibrillation", [r"atrial fibrillation", r"\ba-?fib\b", r"\baf\b(?! ?\d)"],
            codes=["SNOMED:49436004"]),
    Concept("stroke", "Stroke / cerebrovascular accident",
            [r"stroke", r"cerebrovascular accident", r"\bcva\b", r"transient ischemic attack", r"transient ischaemic attack", r"\btia\b"],
            codes=["SNOMED:230690007"]),
    Concept("chronic_kidney_disease", "Chronic kidney disease",
            [r"chronic kidney disease", r"\bckd\b", r"chronic renal (?:failure|insufficiency|disease)", r"end[- ]stage renal",
             r"\besrd\b", r"renal insufficiency", r"kidney failure", r"renal failure", r"dialysis"],
            codes=["SNOMED:709044004"]),
    Concept("copd", "Chronic obstructive pulmonary disease",
            [r"chronic obstructive (?:pulmonary|lung) disease", r"\bcopd\b", r"emphysema", r"chronic (?:obstructive )?bronchitis"],
            codes=["SNOMED:13645005"]),
    Concept("asthma", "Asthma", [r"asthma\w*"], codes=["SNOMED:195967001"]),
    Concept("obesity", "Obesity", [r"obes\w*", r"body mass index 30\+", r"morbid(?:ly)? obes\w*"], codes=["SNOMED:414916001"]),
    Concept("hyperlipidemia", "Hyperlipidemia",
            [r"hyperlipid\w*", r"dyslipid\w*", r"hypercholesterol\w*", r"hypertriglycerid\w*", r"high cholesterol"],
            codes=["SNOMED:55822004"]),
    Concept("cancer", "Malignancy (any)",
            [r"malignan\w*", r"cancer\w*", r"carcinoma\w*", r"neoplasm\w*", r"tumou?rs?\b", r"lymphoma\w*", r"leuka?emia\w*",
             r"melanoma\w*", r"sarcoma\w*", r"myeloma\w*", r"glioma\w*", r"glioblastoma\w*", r"astrocytoma\w*"],
            exclude=[r"benign", r"non-?melanoma skin", r"basal cell", r"squamous cell (?:carcinoma )?of the skin", r"in situ",
                     r"suspected"],
            codes=["SNOMED:363346000"]),
    Concept("breast_cancer", "Breast cancer", [r"breast (?:cancer|carcinoma|neoplasm|tumou?r)", r"malignant neoplasm of breast"],
            codes=["SNOMED:254837009"]),
    Concept("lung_cancer", "Lung cancer", [r"lung (?:cancer|carcinoma|adenocarcinoma)", r"\bnsclc\b", r"\bsclc\b",
                                           r"non-?small[- ]cell lung", r"small[- ]cell (?:lung )?carcinoma"],
            exclude=[r"suspected"], codes=["SNOMED:254637007"]),
    Concept("colorectal_cancer", "Colorectal cancer", [r"colo-?rectal (?:cancer|carcinoma)", r"colon (?:cancer|carcinoma)",
                                                       r"rectal (?:cancer|carcinoma)", r"malignant neoplasm of colon"],
            codes=["SNOMED:363406005"]),
    Concept("prostate_cancer", "Prostate cancer", [r"prostat\w* (?:cancer|carcinoma|adenocarcinoma)", r"neoplasm of prostate"],
            exclude=[r"suspected"], codes=["SNOMED:399068003"]),
    Concept("depression", "Depression", [r"depressi\w*", r"major depressive", r"\bmdd\b"],
            exclude=[r"respiratory depression", r"st[- ]segment depression", r"bone marrow depression"],
            codes=["SNOMED:370143000"]),
    Concept("anxiety", "Anxiety disorder", [r"anxiety disorder", r"generali[sz]ed anxiety", r"\bgad\b", r"severe anxiety", r"panic disorder"], codes=["SNOMED:197480006"]),
    Concept("schizophrenia", "Schizophrenia / psychosis", [r"schizophren\w*", r"psychos[ie]s", r"psychotic"], codes=["SNOMED:58214004"]),
    Concept("bipolar", "Bipolar disorder", [r"bipolar"], codes=["SNOMED:13746004"]),
    Concept("dementia", "Dementia / Alzheimer's", [r"dementia", r"alzheimer\w*", r"cognitive impairment"], codes=["SNOMED:52448006"]),
    Concept("epilepsy", "Epilepsy / seizures", [r"epilep\w*", r"seizure\w*", r"convulsi\w*"], codes=["SNOMED:84757009"]),
    Concept("parkinsons", "Parkinson's disease", [r"parkinson\w*"], codes=["SNOMED:49049000"]),
    Concept("hiv", "HIV infection", [r"\bhiv\b", r"human immunodeficiency virus", r"\baids\b"], codes=["SNOMED:86406008"]),
    Concept("hepatitis_b", "Hepatitis B", [r"hepatitis b", r"\bhbv\b", r"hbsag"], codes=["SNOMED:66071002"]),
    Concept("hepatitis_c", "Hepatitis C", [r"hepatitis c", r"\bhcv\b"], codes=["SNOMED:50711007"]),
    Concept("liver_disease", "Liver disease / cirrhosis",
            [r"cirrhos[ie]s", r"liver disease", r"hepatic (?:impairment|insufficiency|disease|failure)", r"liver failure", r"\bnash\b", r"\bnafld\b",
             r"fatty liver"],
            codes=["SNOMED:235856003"]),
    Concept("pregnancy", "Pregnancy / lactation",
            [r"pregnan\w*", r"lactat\w*", r"breast-?\s?feeding", r"nursing mothers?"],
            exclude=[r"pregnancy test", r"prevent(?:ing)? pregnancy", r"childbearing", r"history of miscarriage"],
            codes=["SNOMED:77386006"], acute=True),
    Concept("rheumatoid_arthritis", "Rheumatoid arthritis", [r"rheumatoid arthritis", r"\bra\b(?= patients| disease)"], codes=["SNOMED:69896004"]),
    Concept("osteoarthritis", "Osteoarthritis", [r"osteoarthrit\w*"], codes=["SNOMED:396275006"]),
    Concept("osteoporosis", "Osteoporosis", [r"osteoporo\w*"], codes=["SNOMED:64859006"]),
    Concept("hypothyroidism", "Hypothyroidism", [r"hypothyroid\w*"], codes=["SNOMED:40930008"]),
    Concept("anemia", "Anaemia", [r"an(?:a)?emi(?:a|c)"], codes=["SNOMED:271737000"]),
    Concept("sleep_apnea", "Obstructive sleep apnoea", [r"sleep apn(?:o)?ea", r"\bosa\b"], codes=["SNOMED:78275009"]),
    Concept("substance_use", "Substance / alcohol use disorder",
            [r"substance (?:ab)?use", r"drug (?:ab)?use", r"alcohol (?:ab)?use", r"alcoholism", r"drug addiction", r"opioid (?:ab)?use",
             r"alcohol dependence", r"drug dependence"],
            codes=["SNOMED:66214007"]),
    Concept("smoker", "Current tobacco smoker", [r"current(?:ly)? smok\w*", r"smokes tobacco", r"active smok\w*", r"tobacco use"],
            codes=["SNOMED:77176002"]),
    Concept("sepsis", "Sepsis / active infection", [r"sepsis", r"septic", r"active infection", r"uncontrolled infection"],
            codes=["SNOMED:91302008"], acute=True),
    Concept("organ_transplant", "Organ transplant", [r"(?:organ|kidney|renal|liver|heart|lung) transplant\w*", r"transplant recipient"],
            codes=["SNOMED:161663000"]),
    Concept("diabetic_retinopathy", "Diabetic retinopathy", [r"diabetic retinopathy", r"proliferative retinopathy"], codes=["SNOMED:4855003"]),
    Concept("neuropathy", "Peripheral neuropathy", [r"neuropath\w*"], codes=["SNOMED:302226006"]),
    Concept("gout", "Gout", [r"\bgout\w*"], codes=["SNOMED:90560007"]),
    Concept("pancreatitis", "Pancreatitis", [r"pancreatitis"], codes=["SNOMED:75694006"]),
    Concept("covid19", "COVID-19", [r"covid-?19", r"sars-?cov-?2", r"severe acute respiratory syndrome coronavirus 2"],
            exclude=[r"suspected"], codes=["SNOMED:840539006"], acute=True),
]

# --------------------------------------------------------------------------- medications
MEDICATIONS: list[Concept] = [
    Concept("metformin", "Metformin", [r"metformin"], codes=["RxNorm:6809"]),
    Concept("insulin", "Insulin", [r"insulin(?! resistance| sensitiv| level| secret)", r"glargine", r"detemir", r"degludec", r"lispro",
                                   r"aspart", r"humulin", r"novolin"], codes=["RxNorm:5856"]),
    Concept("sulfonylurea", "Sulfonylurea", [r"sulfonylurea\w*", r"glipizide", r"glyburide", r"glibenclamide", r"glimepiride", r"gliclazide"]),
    Concept("sglt2", "SGLT2 inhibitor", [r"sglt-?2", r"empagliflozin", r"dapagliflozin", r"canagliflozin", r"ertugliflozin"]),
    Concept("glp1", "GLP-1 receptor agonist", [r"glp-?1", r"semaglutide", r"liraglutide", r"dulaglutide", r"exenatide", r"tirzepatide"]),
    Concept("dpp4", "DPP-4 inhibitor", [r"dpp-?4", r"sitagliptin", r"saxagliptin", r"linagliptin", r"alogliptin", r"vildagliptin"]),
    Concept("anticoagulant", "Anticoagulant", [r"anticoagula\w*", r"warfarin", r"apixaban", r"rivaroxaban", r"dabigatran", r"edoxaban",
                                               r"heparin", r"enoxaparin", r"coumadin"]),
    Concept("antiplatelet", "Antiplatelet", [r"antiplatelet", r"clopidogrel", r"ticagrelor", r"prasugrel", r"aspirin"]),
    Concept("statin", "Statin", [r"statins?\b", r"atorvastatin", r"simvastatin", r"rosuvastatin", r"pravastatin", r"lovastatin"]),
    Concept("ace_arb", "ACE inhibitor / ARB", [r"ace[- ]inhibitor\w*", r"\bacei\b", r"\barbs?\b", r"angiotensin", r"lisinopril", r"enalapril",
                                               r"ramipril", r"losartan", r"valsartan", r"candesartan", r"telmisartan"]),
    Concept("beta_blocker", "Beta blocker", [r"beta[- ]?blocker\w*", r"metoprolol", r"atenolol", r"carvedilol", r"bisoprolol", r"propranolol"]),
    Concept("corticosteroid", "Systemic corticosteroid", [r"corticosteroid\w*", r"glucocorticoid\w*", r"\bsteroids?\b", r"prednison\w*",
                                                          r"prednisolon\w*", r"dexamethason\w*", r"methylprednisolon\w*", r"hydrocortison\w*"]),
    Concept("immunosuppressant", "Immunosuppressant", [r"immunosuppress\w*", r"tacrolimus", r"cyclosporin\w*", r"mycophenolat\w*",
                                                       r"azathioprin\w*", r"sirolimus"]),
    Concept("chemotherapy", "Chemotherapy", [r"chemotherap\w*", r"cytotoxic", r"cisplatin", r"carboplatin", r"paclitaxel", r"docetaxel",
                                             r"doxorubicin", r"cyclophosphamide", r"fluorouracil", r"5-fu"]),
    Concept("opioid", "Opioid", [r"opioid\w*", r"opiate\w*", r"morphine", r"oxycodone", r"hydrocodone", r"fentanyl", r"tramadol", r"methadone"]),
    Concept("nsaid", "NSAID", [r"nsaids?", r"ibuprofen", r"naproxen", r"diclofenac", r"celecoxib"]),
    Concept("cyp3a4_inhibitor", "Strong CYP3A4 inhibitor", [r"cyp\s?3a4? inhibitor\w*", r"ketoconazole", r"itraconazole", r"clarithromycin",
                                                            r"ritonavir"]),
]

# --------------------------------------------------------------------------- labs
@dataclass
class Lab:
    key: str
    label: str
    unit: str
    patterns: list[str]
    loinc: list[str]
    uln: float | None = None  # upper limit of normal, for "x ULN" thresholds
    _rx: re.Pattern | None = None

    def __post_init__(self):
        self._rx = re.compile(r"(?<![\w-])(?:" + "|".join(self.patterns) + r")(?![\w])", re.I)


LABS: list[Lab] = [
    Lab("hba1c", "HbA1c", "%", [r"hb\s?a1c", r"hemoglobin a1c", r"haemoglobin a1c", r"a1c", r"glyc(?:at|osyl)ated ha?emoglobin"],
        ["4548-4", "17856-6"]),
    Lab("egfr", "eGFR", "mL/min/1.73m²", [r"e?gfr", r"(?:estimated )?glomerular filtration rate", r"creatinine clearance", r"crcl"],
        ["33914-3", "62238-1", "98979-8", "69405-9", "48642-3", "48643-1"]),
    Lab("creatinine", "Serum creatinine", "mg/dL", [r"(?:serum )?creatinine(?! clearance)", r"\bscr\b"], ["2160-0", "38483-4"], uln=1.2),
    Lab("bmi", "BMI", "kg/m²", [r"bmi", r"body mass index"], ["39156-5"]),
    Lab("sbp", "Systolic BP", "mmHg", [r"systolic(?: blood pressure| bp)?", r"\bsbp\b"], ["8480-6"]),
    Lab("dbp", "Diastolic BP", "mmHg", [r"diastolic(?: blood pressure| bp)?", r"\bdbp\b"], ["8462-4"]),
    Lab("ldl", "LDL cholesterol", "mg/dL", [r"ldl(?:-c)?(?: cholesterol)?", r"low[- ]density lipoprotein(?: cholesterol)?"], ["18262-6", "13457-7"]),
    Lab("hdl", "HDL cholesterol", "mg/dL", [r"hdl(?:-c)?(?: cholesterol)?", r"high[- ]density lipoprotein"], ["2085-9"]),
    Lab("total_cholesterol", "Total cholesterol", "mg/dL", [r"total cholesterol", r"serum cholesterol"], ["2093-3"]),
    Lab("triglycerides", "Triglycerides", "mg/dL", [r"triglycerides?", r"\btg\b"], ["2571-8"]),
    Lab("glucose", "Fasting glucose", "mg/dL", [r"fasting (?:plasma |blood )?glucose", r"\bfpg\b", r"blood glucose", r"plasma glucose"],
        ["2339-0", "1558-6", "2345-7"]),
    Lab("hemoglobin", "Haemoglobin", "g/dL", [r"ha?emoglobin(?! a1c)", r"\bhgb\b", r"\bhb\b(?!\s?a1c)"], ["718-7"]),
    Lab("platelets", "Platelet count", "×10³/µL", [r"platelets?(?: count)?", r"\bplt\b"], ["777-3", "26515-7"]),
    Lab("wbc", "WBC count", "×10³/µL", [r"white blood cells?(?: count)?", r"\bwbc\b", r"leukocytes?(?: count)?"], ["6690-2", "26464-8"]),
    Lab("alt", "ALT", "U/L", [r"\balt\b", r"alanine aminotransferase", r"\bsgpt\b"], ["1742-6"], uln=40),
    Lab("ast", "AST", "U/L", [r"\bast\b", r"aspartate aminotransferase", r"\bsgot\b"], ["1920-8"], uln=40),
    Lab("bilirubin", "Total bilirubin", "mg/dL", [r"(?:total |serum )?bilirubin"], ["1975-2"], uln=1.2),
    Lab("potassium", "Potassium", "mmol/L", [r"potassium", r"\bk\+"], ["2823-3", "6298-4"]),
    Lab("sodium", "Sodium", "mmol/L", [r"sodium", r"\bna\+"], ["2951-2", "2947-0"]),
    Lab("weight", "Body weight", "kg", [r"body weight", r"weigh(?:t|ing)"], ["29463-7"]),
    Lab("lvef", "LVEF", "%", [r"lvef", r"left ventricular ejection fraction", r"ejection fraction", r"\bef\b"], ["10230-1", "18043-0"]),
]

LAB_BY_KEY = {lab.key: lab for lab in LABS}
LOINC_TO_LAB = {code: lab.key for lab in LABS for code in lab.loinc}
CONCEPT_BY_KEY = {c.key: c for c in CONDITIONS + MEDICATIONS}

# Hierarchy: a patient with a child concept also "has" the parent.
PARENTS = {
    "breast_cancer": ["cancer"], "lung_cancer": ["cancer"], "colorectal_cancer": ["cancer"], "prostate_cancer": ["cancer"],
    "myocardial_infarction": ["coronary_artery_disease"],
}


def find_concepts(text: str, vocab: list[Concept]) -> list[tuple[Concept, re.Match]]:
    """All non-overlapping concept mentions, most specific (longest) first."""
    hits: list[tuple[Concept, re.Match]] = []
    for c in vocab:
        for m in c.finditer(text):
            hits.append((c, m))
    hits.sort(key=lambda h: (-(h[1].end() - h[1].start()), h[1].start()))
    taken: list[tuple[int, int]] = []
    out = []
    for c, m in hits:
        if any(m.start() < e and s < m.end() for s, e in taken):
            continue
        taken.append((m.start(), m.end()))
        out.append((c, m))
    out.sort(key=lambda h: h[1].start())
    return out


def classify_display(display: str, vocab: list[Concept]) -> list[str]:
    """Map a coded-record display string (e.g. Synthea) to concept keys incl. parents."""
    keys = {c.key for c, _ in find_concepts(display, vocab)}
    for k in list(keys):
        keys.update(PARENTS.get(k, []))
    return sorted(keys)
