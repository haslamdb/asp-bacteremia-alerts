"""Mock clinical notes for testing and demo purposes."""

from datetime import datetime, timedelta
from ..models import ClinicalNote


class MockNoteSource:
    """Generates mock clinical notes for testing.

    Creates a mix of relevant and irrelevant notes to test
    keyword filtering performance. Notes are realistic length
    (2-3K characters each) to simulate actual EHR documentation.
    """

    # Notes WITH CLABSI-relevant keywords (should be kept by filter)
    CLABSI_RELEVANT_NOTES = [
        {
            "note_type": "id_consult",
            "content": """INFECTIOUS DISEASE CONSULTATION

Date of Consult: Hospital Day 8
Reason for Consult: Positive blood cultures with central line in place

HISTORY OF PRESENT ILLNESS:
This is a 45-year-old male with history of acute myeloid leukemia currently receiving induction chemotherapy who was admitted 8 days ago for neutropenic fever. He has a right subclavian triple-lumen central venous catheter that was placed 12 days ago for chemotherapy administration.

The patient developed fever to 102.4F yesterday with rigors. Blood cultures were drawn from the central line and peripherally. Preliminary results show gram-positive cocci in clusters growing in 2/2 central line cultures drawn at 14:32 and 2/2 peripheral cultures drawn at 14:45. Differential time to positivity shows central line cultures turned positive approximately 2 hours before peripheral cultures, suggesting catheter-related bloodstream infection.

The patient reports no erythema or drainage at the catheter exit site. He denies any other localizing symptoms. He has been on piperacillin-tazobactam for neutropenic fever coverage since admission.

PAST MEDICAL HISTORY:
1. Acute myeloid leukemia - diagnosed 3 weeks ago
2. Hypertension
3. Type 2 diabetes mellitus
4. No prior central line infections

CURRENT MEDICATIONS:
1. Piperacillin-tazobactam 4.5g IV q6h
2. Fluconazole 400mg IV daily
3. Acyclovir 400mg PO BID
4. Metformin 1000mg PO BID (held)
5. Lisinopril 10mg PO daily

ALLERGIES: Penicillin (rash as child - tolerating pip-tazo without issue)

PHYSICAL EXAMINATION:
Vitals: T 101.2F, HR 105, BP 118/72, RR 18, SpO2 97% RA
General: Ill-appearing, but alert and oriented
HEENT: Mucositis present, no thrush
Neck: Right subclavian CVC in place, exit site clean without erythema, drainage, or tenderness. No tunnel tenderness.
Cardiovascular: Tachycardic, regular rhythm, no murmurs
Lungs: Clear to auscultation bilaterally
Abdomen: Soft, non-tender, no hepatosplenomegaly
Extremities: No peripheral edema, no signs of septic emboli
Skin: No petechiae or purpura

LABORATORY DATA:
WBC: 0.2 K/uL (ANC 0)
Hemoglobin: 8.2 g/dL
Platelets: 45 K/uL
Creatinine: 1.1 mg/dL
Lactate: 1.8 mmol/L

Blood cultures: Gram-positive cocci in clusters (preliminary)
- Central line cultures (x2): Positive at 12 hours
- Peripheral cultures (x2): Positive at 14 hours

ASSESSMENT AND PLAN:
1. CATHETER-RELATED BLOODSTREAM INFECTION (CRBSI)
Most likely coagulase-negative Staphylococcus given gram stain, though S. aureus cannot be ruled out pending speciation and sensitivities. Differential time to positivity of 2 hours supports catheter as the source.

Given the patient's need for ongoing central access for chemotherapy and current hemodynamic stability, we will attempt catheter salvage with antibiotic lock therapy if organism is coagulase-negative Staph with favorable sensitivities.

Recommendations:
a) Add vancomycin 1.5g IV q12h for gram-positive coverage
b) Continue piperacillin-tazobactam for neutropenic fever protocol
c) Await culture speciation and sensitivities
d) If MSSA or MRSA: Remove central line, as S. aureus bacteremia requires line removal
e) If coagulase-negative Staph: Can attempt line salvage with antibiotic lock therapy
f) Repeat blood cultures in 48-72 hours to document clearance
g) TTE to rule out endocarditis if S. aureus or persistent bacteremia
h) Daily surveillance cultures until negative x 48 hours

Will follow closely. Please call with culture results.

_____________________
Dr. Sarah Chen, MD
Infectious Disease Fellow
Pager: 555-1234
"""
        },
        {
            "note_type": "progress_note",
            "content": """MEDICINE PROGRESS NOTE - Hospital Day 9

SUBJECTIVE:
Patient reports feeling "a little better" today. Fever has resolved overnight. No new rigors or chills. Tolerating oral intake. Central line site unchanged - no pain, redness, or drainage. Denies cough, shortness of breath, abdominal pain, diarrhea, or dysuria.

OVERNIGHT EVENTS:
- Tmax 99.8F (down from 102.4F yesterday)
- Started on vancomycin per ID recommendations
- Blood cultures from yesterday growing Staphylococcus epidermidis (coagulase-negative)
- Sensitivities pending

OBJECTIVE:
Vitals: T 98.9F, HR 88, BP 125/78, RR 16, SpO2 98% RA
General: Alert, comfortable, appears improved from yesterday
Central Line Site: Right subclavian triple-lumen catheter, dressing clean and intact, no erythema at exit site, no tunnel tenderness, catheter flushes well in all lumens
Cardiovascular: Regular rate and rhythm, no murmurs appreciated
Lungs: Clear bilaterally
Abdomen: Soft, non-tender
Extremities: No edema, no Janeway lesions or Osler nodes

Labs:
WBC: 0.3 K/uL (still neutropenic, ANC 10)
Hgb: 7.9 g/dL - will transfuse 1 unit pRBC
Platelets: 38 K/uL
Creatinine: 1.0 mg/dL
Vancomycin trough: Pending (due before 4th dose)

Microbiology:
Blood cultures (yesterday): Staphylococcus epidermidis 4/4 bottles
- Final sensitivities pending
- Preliminary: Likely methicillin-resistant based on rapid testing

ASSESSMENT/PLAN:
45-year-old male with AML on induction chemotherapy, neutropenic fever, now with CENTRAL LINE ASSOCIATED BLOODSTREAM INFECTION (CLABSI) secondary to Staphylococcus epidermidis (coagulase-negative Staph).

1. CLABSI - Coagulase-negative Staph bacteremia
- Continue vancomycin, adjust dose based on trough level
- ID recommends attempt at line salvage given CoNS and hemodynamic stability
- Will add antibiotic lock therapy once sensitivities confirmed
- Repeat blood cultures today to document clearance
- If persistent bacteremia at 72 hours, will need to remove line
- Defer TTE unless bacteremia persists or clinical deterioration

2. Neutropenic fever - improving
- Continue piperacillin-tazobactam per neutropenic fever protocol
- Await count recovery

3. Anemia - transfuse 1 unit pRBC today

4. AML - continue supportive care, await count recovery

Will discuss with oncology attending regarding chemotherapy timing.

_____________________
Dr. Michael Torres, MD
Internal Medicine Resident PGY-2
"""
        },
        {
            "note_type": "progress_note",
            "content": """MEDICINE PROGRESS NOTE - Hospital Day 11

SUBJECTIVE:
Patient continues to improve. Afebrile for 48 hours. Central line flushing well, site looks good. Patient eager to continue with chemotherapy when counts recover. No new complaints.

OVERNIGHT EVENTS:
- Remained afebrile
- Repeat blood cultures from day 9 returned NO GROWTH at 48 hours
- ANC showing early recovery (now 180)
- Vancomycin trough therapeutic at 15.2

OBJECTIVE:
Vitals: T 98.4F, HR 76, BP 130/82, RR 14, SpO2 99% RA
General: Alert, comfortable, appears well
Central Line: Right subclavian CVC intact, site without erythema or drainage, no tenderness. Antibiotic lock in place.
Cardiovascular: Regular rate and rhythm
Lungs: Clear
Abdomen: Soft, non-tender

Labs:
WBC: 1.2 K/uL (ANC 180 - recovering!)
Hgb: 9.1 g/dL post-transfusion
Platelets: 52 K/uL
Vancomycin trough: 15.2 mcg/mL (therapeutic)

Microbiology Update:
- Original cultures: Staphylococcus epidermidis, methicillin-resistant
- Sensitivities: Resistant to oxacillin, sensitive to vancomycin (MIC 1), daptomycin, linezolid
- Repeat cultures (day 9): No growth at 48 hours - CLEARANCE DOCUMENTED

ASSESSMENT/PLAN:
45M with AML, induction chemotherapy, CLABSI secondary to MRSE, now with documented bloodstream clearance. Line salvage appears successful.

1. CLABSI - MRSE, cleared
- Continue vancomycin x 14 days from first negative culture (day 9)
- Continue antibiotic lock therapy for duration of IV antibiotics
- Line salvage successful - may continue to use central line
- Surveillance cultures not needed if patient remains afebrile
- ID following, will sign off if continues to do well

2. Neutropenia - recovering
- ANC 180 today, expected continued recovery
- Can discontinue piperacillin-tazobactam once ANC > 500 x 2 days
- Continue neutropenic precautions until ANC > 500

3. AML
- Discuss with oncology regarding timing of consolidation chemotherapy
- Will need repeat bone marrow biopsy to assess response

Central line can remain in place for ongoing chemotherapy needs.

_____________________
Dr. Michael Torres, MD
"""
        },
        {
            "note_type": "nursing_note",
            "content": """NURSING ASSESSMENT AND CARE NOTE

Date/Time: 0700-1900 Shift
Patient: 45-year-old male, AML, central line infection

VITAL SIGNS TREND:
0800: T 98.6, HR 78, BP 128/76, RR 16, SpO2 98% RA
1200: T 98.8, HR 82, BP 132/80, RR 14, SpO2 99% RA
1600: T 98.4, HR 76, BP 126/78, RR 16, SpO2 98% RA

CENTRAL LINE ASSESSMENT:
- Type: Triple-lumen central venous catheter, right subclavian
- Insertion date: 12 days ago
- Dressing: Clean, dry, intact. Tegaderm with date marked.
- Exit site: No erythema, swelling, or drainage
- Tunnel: No tenderness on palpation
- Lumens: All three flush freely, no resistance
- Antibiotic lock: Vancomycin lock instilled per protocol at 0800 after labs drawn

CENTRAL LINE CARE PROVIDED:
- Assessed site every 4 hours per CLABSI bundle
- Hand hygiene performed before and after line access
- Scrubbed hub for 15 seconds with alcohol before each access
- Line accessed only for necessary medications and lab draws
- Documented all line accesses in flowsheet

MEDICATIONS ADMINISTERED VIA CENTRAL LINE:
- Vancomycin 1.25g IV at 0600 (infused via dedicated lumen)
- Piperacillin-tazobactam 4.5g IV at 0600, 1200, 1800
- Fluconazole 400mg IV at 0800
- Normal saline flushes after each medication

IV SITE (PERIPHERAL):
- 20g IV left forearm placed yesterday as backup
- Site without redness or swelling
- Flushes without difficulty

INTAKE/OUTPUT:
Intake: 2400mL (IV fluids 1800mL, PO 600mL)
Output: 2100mL (urine)

PATIENT EDUCATION PROVIDED:
- Reinforced importance of reporting any fever, chills, or redness at line site
- Explained purpose of antibiotic lock therapy
- Reviewed neutropenic precautions
- Patient verbalized understanding

PLAN FOR NEXT SHIFT:
- Continue central line assessments q4h
- Vancomycin due at 1800
- Monitor for signs of infection or line complications
- Blood cultures pending - check for results

_____________________
Sarah Johnson, RN, BSN
"""
        },
        {
            "note_type": "progress_note",
            "content": """INFECTIOUS DISEASE FOLLOW-UP NOTE

Hospital Day 10

Consulted for ongoing management of central line-associated bloodstream infection.

INTERVAL HISTORY:
Patient with MRSE CLABSI, started on vancomycin 3 days ago. Clinically improving - afebrile x 24 hours, hemodynamically stable. Repeat blood cultures drawn yesterday are pending. Central line remains in place for ongoing chemotherapy needs.

CURRENT ANTIBIOTICS:
- Vancomycin 1.25g IV q12h (day 3) - trough 15.2 (therapeutic)
- Vancomycin antibiotic lock therapy initiated yesterday
- Piperacillin-tazobactam continuing for neutropenic fever protocol

PHYSICAL EXAM:
Afebrile, comfortable
Central line exit site: Clean, no erythema, no tenderness
No stigmata of endocarditis

MICROBIOLOGY REVIEW:
Original blood cultures (4/4 positive):
- Staphylococcus epidermidis
- Methicillin-resistant (oxacillin MIC > 2)
- Vancomycin MIC 1 mcg/mL (susceptible)
- No inducible clindamycin resistance

Repeat cultures: Pending (drawn 18 hours ago)

ASSESSMENT:
CLABSI secondary to MRSE, clinically responding to vancomycin therapy. Given:
1. Coagulase-negative Staphylococcus (not S. aureus)
2. Patient hemodynamically stable
3. No tunnel infection or exit site infection
4. Need for ongoing central venous access for chemotherapy
5. Clinical improvement on appropriate antibiotics

We support attempt at catheter salvage with antibiotic lock therapy.

RECOMMENDATIONS:
1. Continue vancomycin 1.25g IV q12h, dose adjusted for trough 15-20
2. Continue vancomycin antibiotic lock therapy (vancomycin 5mg/mL, dwell minimum 12 hours)
3. Total duration: 14 days from first negative blood culture
4. If repeat cultures positive at 72 hours -> catheter removal required
5. If cultures remain negative and patient stable -> continue current plan
6. TTE not indicated unless S. aureus identified or persistent bacteremia
7. No ophthalmology consult needed for CoNS bacteremia
8. Piperacillin-tazobactam can be discontinued once ANC > 500 per oncology

Will continue to follow. Call with culture results.

_____________________
Dr. Sarah Chen, MD
Infectious Disease
"""
        },
        {
            "note_type": "discharge_summary",
            "content": """DISCHARGE SUMMARY

PATIENT: 45-year-old male
ADMISSION DATE: [14 days ago]
DISCHARGE DATE: [Today]
LENGTH OF STAY: 14 days

PRINCIPAL DIAGNOSIS:
1. Central line-associated bloodstream infection (CLABSI), methicillin-resistant Staphylococcus epidermidis

SECONDARY DIAGNOSES:
2. Acute myeloid leukemia, status post induction chemotherapy
3. Neutropenic fever, resolved
4. Anemia requiring transfusion
5. Hypertension
6. Type 2 diabetes mellitus

HOSPITAL COURSE:

This 45-year-old male with newly diagnosed AML was admitted for induction chemotherapy. A right subclavian triple-lumen central venous catheter had been placed prior to admission for chemotherapy administration.

NEUTROPENIC FEVER/CLABSI:
On hospital day 8, the patient developed fever to 102.4F with rigors. Blood cultures were drawn from the central line and peripherally, both growing gram-positive cocci. Vancomycin was added to the piperacillin-tazobactam he was already receiving for neutropenic fever prophylaxis.

Cultures speciated to Staphylococcus epidermidis (coagulase-negative), methicillin-resistant but vancomycin-susceptible. Differential time to positivity (central line positive 2 hours before peripheral) supported catheter-related bloodstream infection. Infectious Disease was consulted and recommended attempt at catheter salvage with antibiotic lock therapy given the organism (CoNS, not S. aureus), patient stability, and need for ongoing central access.

Repeat blood cultures 48 hours after starting vancomycin showed no growth, documenting clearance. The patient defervesced and remained afebrile for the remainder of the hospitalization. He completed a 14-day course of vancomycin from the first negative blood culture, with antibiotic lock therapy throughout. The central line was successfully salvaged and remains in place for ongoing chemotherapy.

AML TREATMENT:
The patient tolerated induction chemotherapy. Bone marrow biopsy on day 14 showed hypocellular marrow with no definite residual leukemia. He will follow up with oncology for consolidation chemotherapy planning.

NEUTROPENIA:
ANC recovered to > 500 on hospital day 12. Neutropenic precautions and piperacillin-tazobactam were discontinued at that time.

DISCHARGE MEDICATIONS:
1. Vancomycin 1.25g IV q12h - COMPLETED (last dose given this AM)
2. Lisinopril 10mg PO daily
3. Metformin 1000mg PO BID (resume home dose)
4. Acyclovir 400mg PO BID
5. Fluconazole 400mg PO daily x 7 more days

CENTRAL LINE STATUS AT DISCHARGE:
- Right subclavian triple-lumen CVC remains in place
- Functioning well, no signs of infection
- May be used for outpatient lab draws and future chemotherapy
- Standard line care to continue

FOLLOW-UP:
1. Oncology clinic in 1 week for chemotherapy planning
2. Infectious Disease clinic in 2 weeks (Dr. Chen)
3. PCP follow-up in 2 weeks
4. Labs: CBC, CMP in 1 week

DISCHARGE CONDITION: Stable, improved

DISCHARGE INSTRUCTIONS:
- Monitor for fever, chills, redness/drainage at line site - call or return immediately
- Keep line site clean and dry
- Return to ED for temperature > 100.4F

_____________________
Dr. Michael Torres, MD
Attending: Dr. Jennifer Williams, MD
"""
        },
        {
            "note_type": "progress_note",
            "content": """ONCOLOGY PROGRESS NOTE - Hospital Day 7

SUBJECTIVE:
Patient with newly diagnosed AML status post day 7 of 7+3 induction chemotherapy. Completed cytarabine and daunorubicin as scheduled. Currently profoundly neutropenic as expected. Reports fatigue but otherwise feels okay. No fevers at home prior to admission. Has noted some mouth sores developing.

No cough, shortness of breath, chest pain. No abdominal pain, nausea, vomiting, diarrhea. No dysuria or urinary symptoms. No rashes or skin changes. No bleeding.

OBJECTIVE:
Vitals: T 98.2F, HR 80, BP 122/74, RR 16, SpO2 98% RA
General: Tired-appearing but alert, no acute distress
HEENT: Mild mucositis, grade 1
Neck: Central venous catheter right subclavian, site clean
Lungs: Clear bilaterally
Heart: Regular rate and rhythm
Abdomen: Soft, non-tender
Skin: No rashes, no petechiae

Labs:
WBC: 0.1 K/uL (ANC 0)
Hgb: 8.8 g/dL
Platelets: 22 K/uL (transfuse)
Creatinine: 0.9 mg/dL

ASSESSMENT/PLAN:
45-year-old male with newly diagnosed AML, completed 7+3 induction, now in expected nadir with profound neutropenia.

1. AML - completed induction
- Await count recovery, expected 2-3 weeks
- Bone marrow biopsy planned for day 14 to assess response
- Discuss consolidation options once response known

2. Neutropenia
- ANC 0, expected nadir
- Continue neutropenic precautions
- Continue prophylactic antimicrobials (levofloxacin, fluconazole, acyclovir)
- Low threshold for blood cultures and empiric antibiotics if fever develops

3. Thrombocytopenia
- Transfuse platelets today for level < 10K or bleeding
- Current platelet count 22K, will recheck in AM

4. Mucositis - grade 1
- Salt water rinses
- Magic mouthwash PRN
- Monitor for worsening

5. Central line
- In place for ongoing treatment
- Site looks good, no concerns
- Will need for blood draws and potential antibiotics if develops fever

Plan to continue supportive care and monitor for infectious complications.

_____________________
Dr. Amanda Price, MD
Hematology/Oncology
"""
        },
        {
            "note_type": "nursing_note",
            "content": """NURSING ADMISSION ASSESSMENT - CLABSI BUNDLE DOCUMENTATION

Patient admitted to unit with central line in place. Performing full CLABSI prevention bundle assessment and documentation.

CENTRAL LINE DETAILS:
- Type: Triple-lumen central venous catheter
- Insertion site: Right subclavian
- Insertion date: 12 days prior to today's assessment
- Line days on admission to this unit: 12
- Placed by: IR under ultrasound guidance
- Indication: Chemotherapy administration

CLABSI BUNDLE COMPLIANCE:
[ X ] Hand hygiene observed before line access
[ X ] Chlorhexidine bathing - patient bathed with CHG wipes this AM
[ X ] Daily assessment of line necessity documented
[ X ] Dressing clean, dry, intact with date labeled
[ X ] Catheter hub scrubbed with alcohol for 15 seconds before access
[ X ] Aseptic technique for all line entries

DAILY LINE NECESSITY ASSESSMENT:
Is central line still needed? YES
Reason: Required for IV chemotherapy, antibiotics, blood product transfusions, and frequent lab draws in setting of AML induction. Peripheral access alone would not be adequate.

SITE ASSESSMENT:
Exit site appearance: Clean, no erythema, no drainage, no tenderness
Sutures/securement: StatLock in place, secure
Dressing type: Tegaderm, dated
Last dressing change: 3 days ago
Tunnel assessment: No tenderness, no erythema along tunnel track

PATENCY CHECK:
Proximal lumen: Flushes freely, good blood return
Middle lumen: Flushes freely, good blood return
Distal lumen: Flushes freely, good blood return

PATIENT/FAMILY EDUCATION:
Educated patient on:
- Signs and symptoms of line infection to report (fever, chills, redness, drainage)
- Importance of keeping dressing clean and dry
- Not to submerge line in water
- To notify nurse if dressing becomes loose or soiled
Patient verbalized understanding and agreement to notify staff of any concerns.

PLAN:
- Continue daily CLABSI bundle compliance
- Dressing change due in 4 days (or sooner if soiled/loose)
- Continue CHG bathing daily
- Assess line necessity daily and document
- Monitor for any signs of infection

_____________________
Jennifer Martinez, RN, BSN
Charge Nurse
"""
        },
    ]

    # Notes WITH SSI-relevant keywords (should be kept by filter)
    SSI_RELEVANT_NOTES = [
        {
            "note_type": "operative_note",
            "content": """OPERATIVE REPORT

PATIENT: 58-year-old male
DATE OF SURGERY: [7 days ago]
SURGEON: Dr. James Peterson, MD
ASSISTANT: Dr. Emily Walsh, MD (Resident)

PREOPERATIVE DIAGNOSIS: Acute perforated appendicitis with localized peritonitis

POSTOPERATIVE DIAGNOSIS: Same

PROCEDURE PERFORMED: Laparoscopic appendectomy converted to open appendectomy

ANESTHESIA: General endotracheal anesthesia

INDICATIONS:
This 58-year-old male presented to the emergency department with 3 days of progressively worsening right lower quadrant abdominal pain, nausea, and fever. CT scan demonstrated a perforated appendix with surrounding inflammatory changes and a small localized fluid collection. Given the findings, the patient was consented for appendectomy.

PROCEDURE IN DETAIL:
After obtaining informed consent, the patient was brought to the operating room and placed in the supine position. General anesthesia was induced and the patient was intubated without difficulty. The abdomen was prepped and draped in sterile fashion. A time-out was performed confirming patient identity, procedure, and surgical site.

Laparoscopic approach was initially attempted. A 12mm incision was made at the umbilicus and a Veress needle was used to establish pneumoperitoneum. A 12mm trocar was placed and the laparoscope was introduced. The appendix was visualized and found to be gangrenous with perforation at the tip and surrounding purulent material. Due to extensive inflammation and difficulty with visualization, decision was made to convert to open procedure.

The umbilical incision was extended and a McBurney incision was also created in the right lower quadrant. The peritoneal cavity was entered. Purulent fluid was encountered and collected for culture. The appendix was identified and found to be necrotic and perforated. The mesoappendix was divided using electrocautery and ligated. The appendiceal base was healthy and was ligated with 2-0 Vicryl sutures and transected. The appendiceal stump was inverted with a purse-string suture. The peritoneal cavity was copiously irrigated with 3 liters of warm normal saline until the effluent was clear.

A Jackson-Pratt drain was placed in the right lower quadrant and brought out through a separate stab incision. The fascia was closed with running 0 PDS suture. The skin was closed loosely with staples given contaminated nature of the case. The umbilical incision was closed primarily. Sterile dressings were applied.

ESTIMATED BLOOD LOSS: 75 mL
FLUIDS: Lactated Ringer's 2500 mL
SPECIMENS: Appendix, peritoneal fluid
DRAINS: 10-French Jackson-Pratt drain to right lower quadrant
COMPLICATIONS: None
DISPOSITION: To PACU in stable condition

ANTIBIOTICS: Piperacillin-tazobactam 4.5g IV given at induction, to continue post-operatively

POST-OPERATIVE PLAN:
1. NPO until return of bowel function
2. IV piperacillin-tazobactam for contaminated surgical field
3. JP drain to gravity, record output
4. Wound care: dry sterile dressing, assess daily
5. DVT prophylaxis with enoxaparin
6. Pain control with PCA
7. Ambulation POD 1

_____________________
Dr. James Peterson, MD, FACS
General Surgery
"""
        },
        {
            "note_type": "progress_note",
            "content": """SURGERY PROGRESS NOTE - Post-Operative Day 3

SUBJECTIVE:
Patient reports improvement in abdominal pain, currently 4/10 (down from 7/10 yesterday). He passed flatus overnight and is tolerating clear liquids without nausea or vomiting. He denies fever, chills, or worsening pain. Reports some discomfort at the incision site but describes it as "normal surgical pain."

OVERNIGHT EVENTS:
- Tmax 100.8F (down from 101.4F POD 2)
- Passed flatus at 0400
- JP drain output 45 mL serosanguinous fluid
- Ambulated twice with assistance

OBJECTIVE:
Vitals: T 99.2F, HR 88, BP 132/78, RR 16, SpO2 97% RA
General: Alert, comfortable, no acute distress
Abdomen: Soft, appropriately tender at surgical sites, bowel sounds present, no distension

INCISION ASSESSMENT:
- Umbilical port site: Clean, dry, approximated, no erythema or drainage
- McBurney incision (RLQ): Staples intact, mild surrounding erythema (2 cm), small amount of serosanguinous drainage on dressing. Wound edges approximated. No fluctuance, no crepitus. Mildly tender to palpation.

JP Drain: In place, output 45 mL/24h, serosanguinous, no purulence

Labs:
WBC: 13.2 K/uL (down from 18.5 on admission)
Hgb: 11.8 g/dL
Creatinine: 1.0 mg/dL

ASSESSMENT/PLAN:
58-year-old male POD 3 from open appendectomy for perforated appendicitis, improving.

1. Post-op perforated appendicitis
- Continue piperacillin-tazobactam, plan for 5-7 day course given perforation
- WBC trending down, fevers improving
- Advance diet to regular as tolerated

2. Surgical wound - McBurney incision
- Some erythema and drainage noted - will monitor closely
- If worsening erythema, increased drainage, or fever, will obtain wound culture
- Continue daily wound assessment
- Dressing changes daily

3. JP drain
- Output decreasing appropriately
- Plan to remove when output < 30 mL/day

4. DVT prophylaxis - continue enoxaparin

5. Pain management - transition to oral pain medication

6. Activity - continue ambulation, increase as tolerated

Anticipate discharge in 2-3 days if continues to improve.

_____________________
Dr. Emily Walsh, MD
Surgery Resident PGY-3
Attending: Dr. James Peterson, MD
"""
        },
        {
            "note_type": "progress_note",
            "content": """SURGERY PROGRESS NOTE - Post-Operative Day 5

SUBJECTIVE:
Patient reports increasing pain at the RLQ incision site overnight, now 6/10. He felt feverish and reports "feeling unwell." He notes the wound dressing was soaked through this morning. Tolerating regular diet, having bowel movements. Denies chest pain, shortness of breath, or calf pain.

OVERNIGHT EVENTS:
- Tmax 101.6F at 0200
- Required additional pain medication overnight
- Dressing saturated with drainage per nursing

OBJECTIVE:
Vitals: T 101.2F, HR 102, BP 128/82, RR 18, SpO2 97% RA
General: Appears uncomfortable, mildly diaphoretic
Abdomen: Soft, increased tenderness around RLQ incision

WOUND EXAMINATION - McBurney Incision:
- Significant erythema extending 4-5 cm beyond wound edges (increased from 2 cm on POD 3)
- Wound edges with early dehiscence at superior aspect, approximately 2 cm separation
- PURULENT DRAINAGE expressed from wound with gentle pressure
- Fluctuance palpable beneath incision - concerning for abscess
- Warmth and induration of surrounding tissue
- No crepitus (no concern for necrotizing infection)

Umbilical port site: Unchanged, healing well

Labs (obtained this AM):
WBC: 18.8 K/uL (was 13.2 on POD 3 - now increasing)
Hgb: 11.4 g/dL
Creatinine: 0.9 mg/dL
Procalcitonin: 1.8 ng/mL

ASSESSMENT/PLAN:
58M POD 5 from open appendectomy for perforated appendicitis now with SURGICAL SITE INFECTION, likely superficial incisional SSI with possible underlying abscess.

1. SURGICAL SITE INFECTION - McBurney incision
- Clinical signs: fever, increasing WBC, wound erythema, purulent drainage, early dehiscence
- WOUND CULTURE obtained from purulent drainage
- Will open wound at bedside for drainage and obtain culture from deeper tissue
- Pack wound with wet-to-dry dressings, change BID
- Consult Wound Care Nurse for wound vac evaluation
- Continue broad-spectrum antibiotics, consider broadening coverage

2. Antibiotics
- Upgrade from piperacillin-tazobactam to add vancomycin empirically pending cultures
- If cultures grow MRSA, will tailor therapy
- Duration will depend on depth of infection and clinical response

3. Imaging
- Obtain CT abdomen/pelvis with contrast to evaluate for deeper abscess
- If significant abscess, may need IR-guided drainage or operative washout

4. JP drain - still in place, output minimal, keep for now given new infection

5. Disposition - discharge delayed, will need continued inpatient wound care

Discussed with patient regarding SSI, wound care plan, and need for extended hospitalization. Patient understands and agrees with plan.

_____________________
Dr. James Peterson, MD, FACS
General Surgery
"""
        },
        {
            "note_type": "id_consult",
            "content": """INFECTIOUS DISEASE CONSULTATION

Date of Consult: Post-operative Day 6
Reason for Consult: Surgical site infection, antibiotic management

HISTORY OF PRESENT ILLNESS:
This is a 58-year-old male who is post-operative day 6 from open appendectomy for perforated appendicitis. He developed signs of surgical site infection on POD 5 including fever to 101.6F, wound erythema, purulent drainage, and early wound dehiscence. The surgical team opened the wound at bedside yesterday and packed with wet-to-dry dressings. CT scan showed a 3 x 2 cm fluid collection at the wound site without deeper intra-abdominal abscess.

Current antibiotics: Piperacillin-tazobactam (since surgery) + vancomycin (added yesterday)

WOUND CULTURE RESULTS (preliminary):
- Gram stain: Many WBC, moderate gram-positive cocci in clusters, moderate gram-negative rods
- Culture: Growing Staphylococcus aureus (sensitivities pending), Escherichia coli (sensitivities pending)

PAST MEDICAL HISTORY:
1. Hypertension
2. Type 2 diabetes mellitus (A1c 7.8%)
3. Obesity (BMI 34)
4. No prior surgical site infections
5. No known MRSA colonization

MEDICATIONS:
1. Piperacillin-tazobactam 4.5g IV q6h
2. Vancomycin 1.5g IV q12h (loading dose given, trough pending)
3. Metformin (held)
4. Lisinopril
5. Enoxaparin

ALLERGIES: None known

PHYSICAL EXAMINATION:
Vitals: T 99.8F (Tmax 100.4F today), HR 90, BP 134/80, RR 16
General: Alert, comfortable, appears improved from yesterday
Abdomen: Soft, mild tenderness RLQ

WOUND EXAMINATION:
- McBurney incision now open, approximately 4 cm x 2 cm x 3 cm deep
- Wound bed with granulation tissue beginning to form
- Surrounding erythema improved (now 2-3 cm, was 4-5 cm)
- Minimal purulent drainage today
- Wound packed with wet-to-dry gauze
- No signs of necrotizing infection (no crepitus, no gray/necrotic tissue)

LABORATORY DATA:
WBC: 14.2 K/uL (down from 18.8 yesterday - improving)
Creatinine: 0.9 mg/dL
Vancomycin trough: 12.3 mcg/mL (slightly low, will adjust)

CT Abdomen/Pelvis (yesterday):
- 3 x 2 cm fluid collection at RLQ surgical site, likely superficial abscess
- No intra-abdominal abscess or undrained collection
- No free air concerning for anastomotic leak (N/A, no anastomosis)

ASSESSMENT:

1. SUPERFICIAL INCISIONAL SURGICAL SITE INFECTION
CDC/NHSN criteria met:
- Infection within 30 days of surgery: YES (POD 5)
- Involves skin and subcutaneous tissue: YES
- Purulent drainage: YES
- Wound culture positive: YES (S. aureus, E. coli)
- Signs/symptoms: fever, erythema, wound dehiscence: YES

Classification: Superficial Incisional SSI (not deep incisional, no involvement of fascia/muscle based on CT; not organ/space, no intra-abdominal abscess)

Organisms: Polymicrobial - this is common for appendicitis-related SSI
- Staphylococcus aureus - skin flora, likely introduced during surgery
- Escherichia coli - enteric flora from perforated appendix

2. ANTIBIOTIC RECOMMENDATIONS:

Current regimen (pip-tazo + vancomycin) provides appropriate empiric coverage.

Once sensitivities return:
- If MSSA (methicillin-susceptible S. aureus):
  - Discontinue vancomycin
  - Continue pip-tazo alone (covers MSSA and E. coli)
  - Consider narrowing to cefazolin if E. coli susceptible

- If MRSA (methicillin-resistant S. aureus):
  - Continue vancomycin, adjust dose for trough 15-20 mcg/mL
  - Can consider switching to oral linezolid or TMP-SMX once wound improving

Duration:
- For superficial SSI with adequate source control (wound open and draining): 7-10 days of antibiotics
- Start counting from POD 5 (onset of infection) = approximately 5-7 more days

3. WOUND CARE RECOMMENDATIONS:
- Continue wet-to-dry dressing changes BID
- Wound vac may be considered once infection controlled to accelerate granulation
- Healing by secondary intention is appropriate

4. VANCOMYCIN DOSING:
- Current trough 12.3 (goal 15-20 for deep infection, but 10-15 acceptable for superficial)
- Adjust dose to vancomycin 1.25g IV q12h, recheck trough in 48 hours

5. BLOOD CULTURES:
- Would recommend peripheral blood cultures to rule out bacteremia, especially given diabetes
- If blood cultures positive, would warrant longer antibiotic course

ADDITIONAL RECOMMENDATIONS:
1. Optimize glycemic control - hyperglycemia impairs wound healing
2. Adequate nutrition - protein supplementation for wound healing
3. Consider zinc and vitamin C supplementation
4. Daily wound assessment by surgical team
5. If wound not improving in 48-72 hours, consider operative debridement

Will continue to follow. Please call with culture sensitivities.

_____________________
Dr. Michael Chen, MD
Infectious Disease
"""
        },
        {
            "note_type": "nursing_note",
            "content": """WOUND CARE NURSING ASSESSMENT

Date/Time: 0930
Patient: 58-year-old male, POD 7 from appendectomy with surgical site infection

REASON FOR CONSULT: Wound vac evaluation for infected surgical wound

WOUND ASSESSMENT - RLQ (McBurney) Incision:

Location: Right lower quadrant, McBurney incision
Wound Type: Surgically opened infected incision, healing by secondary intention

Measurements:
- Length: 5.0 cm
- Width: 2.5 cm
- Depth: 3.5 cm (deepest at center)
- Undermining: 1 cm at 12 o'clock position
- Tunneling: None

Wound Bed:
- 60% red granulation tissue (healthy, beefy appearance)
- 30% yellow slough (fibrinous debris)
- 10% pale/pink epithelializing tissue at edges
- No necrotic tissue present
- No exposed bone, tendon, or hardware

Exudate:
- Amount: Moderate
- Type: Serosanguinous with minimal purulent component (improved from yesterday)
- Odor: Mild (improved from previous assessment)

Periwound Skin:
- Erythema: Present, 2 cm surrounding wound (improving)
- Intact: Yes
- Maceration: Mild at wound edges
- Warmth: Mildly warm
- Induration: Minimal

Pain: Patient reports 4/10 at wound site, 6/10 during dressing changes

Current Dressing: Wet-to-dry normal saline gauze, changed BID

WOUND VAC ASSESSMENT:
Criteria for negative pressure wound therapy (NPWT):
[X] Wound bed adequately debrided
[X] No untreated osteomyelitis
[X] No malignancy in wound
[X] No exposed blood vessels
[X] No necrotic tissue (>20%)
[X] Patient can tolerate therapy

RECOMMENDATION: Patient is a candidate for NPWT (wound vac).

Benefits for this patient:
- Will remove excess exudate
- Promote granulation tissue formation
- Reduce wound size more rapidly
- Reduce frequency of dressing changes (every 48-72h vs BID)
- May shorten hospital stay

WOUND VAC ORDERS REQUESTED:
- V.A.C. Therapy System
- Black GranuFoam dressing
- Continuous pressure at -125 mmHg
- Dressing changes every Monday/Wednesday/Friday
- Canister changes as needed

WOUND VAC PLACEMENT:
Placed wound vac at 1045 after obtaining orders:
- Wound bed irrigated with normal saline and debrided of loose slough
- Black foam cut to wound size and placed in wound bed
- Drape applied with good seal
- Tubing connected, vacuum initiated at -125 mmHg
- Good seal confirmed, foam compressed appropriately
- Patient tolerated procedure well

PATIENT EDUCATION PROVIDED:
- Purpose of wound vac therapy explained
- Signs of complications to report: increased pain, fever, bright red bleeding, foul odor, loss of seal
- Importance of keeping unit plugged in and operational
- Not to disconnect unit without nursing assistance
- How to clamp tubing for brief bathroom use
- Patient and wife verbalized understanding

PLAN:
- Continue wound vac therapy
- Assess seal q shift
- Dressing change in 48-72 hours
- Weekly wound measurements
- Continue current antibiotics per ID
- Nutrition consult placed for wound healing optimization
- Follow for wound vac therapy until wound bed fully granulated

_____________________
Jennifer Adams, RN, CWOCN
Wound Care Nurse Specialist
"""
        },
        {
            "note_type": "progress_note",
            "content": """SURGERY PROGRESS NOTE - Post-Operative Day 10

SUBJECTIVE:
Patient reports significant improvement. Pain at wound site now 2/10, well controlled with oral medication. He is afebrile and feeling "much better." Tolerating regular diet, ambulating independently. Eager to go home. Wound vac has been in place for 3 days.

OBJECTIVE:
Vitals: T 98.4F, HR 78, BP 128/76, RR 14, SpO2 98% RA - All normal
General: Alert, comfortable, no distress, appears well

WOUND ASSESSMENT (wound vac removed for examination):
- McBurney incision wound vac site
- Wound dimensions: 4.5 x 2.0 x 2.5 cm (improved from 5.0 x 2.5 x 3.5 cm)
- Wound bed: 85% granulation tissue (up from 60%), healthy beefy red
- Minimal slough remaining
- Periwound erythema resolved
- No drainage, no purulence
- No odor
- Wound vac replaced with good seal

Labs:
WBC: 9.8 K/uL (normalized)
Hgb: 11.2 g/dL
Creatinine: 0.9 mg/dL

MICROBIOLOGY UPDATE:
Final wound culture results:
- Staphylococcus aureus: METHICILLIN-SUSCEPTIBLE (MSSA)
  - Oxacillin sensitive
  - Vancomycin sensitive (MIC 1)
- Escherichia coli:
  - Ampicillin resistant
  - Ceftriaxone sensitive
  - Ciprofloxacin sensitive
  - TMP-SMX sensitive

Per ID recommendations: Transitioned to oral antibiotics yesterday
- Cephalexin 500mg PO QID (covers MSSA)
- Will complete total 10-day course

ASSESSMENT/PLAN:
58M POD 10 from open appendectomy for perforated appendicitis, s/p superficial SSI now resolving with wound vac therapy and antibiotics.

1. SURGICAL SITE INFECTION - Resolving
- WBC normalized, afebrile
- Wound improving with granulation
- Continue wound vac therapy
- Continue cephalexin to complete 10-day course (4 more days)

2. DISPOSITION - Ready for discharge with wound vac
- Patient and wife trained on wound vac management
- Home health arranged for wound vac dressing changes (M/W/F)
- Durable medical equipment (wound vac unit) arranged

3. FOLLOW-UP:
- Surgery clinic in 1 week for wound check
- Wound vac to be discontinued when wound bed fully granulated (estimated 1-2 weeks)
- ID follow-up not needed unless complications

DISCHARGE INSTRUCTIONS:
- Continue cephalexin 500mg 4x daily until finished (4 days remaining)
- Wound vac: Keep unit on at all times, charge battery when at outlet
- Report: fever >101F, worsening wound drainage, foul smell, increased redness
- Activity: No heavy lifting >10 lbs for 4 weeks, otherwise advance as tolerated
- Diet: Regular, high protein for wound healing
- Return to ED if: fever, severe abdominal pain, wound vac malfunction

DISCHARGE SUMMARY:
This 58-year-old male was admitted for perforated appendicitis requiring open appendectomy. Post-operative course was complicated by superficial incisional surgical site infection (SSI) on POD 5, with wound cultures growing MSSA and E. coli. Wound was opened for drainage and packed. He was treated with IV antibiotics (pip-tazo + vancomycin, later narrowed to cephalexin) and negative pressure wound therapy (wound vac). He responded well and is now stable for discharge with home wound vac and oral antibiotics.

_____________________
Dr. James Peterson, MD, FACS
General Surgery
"""
        },
        {
            "note_type": "discharge_summary",
            "content": """DISCHARGE SUMMARY

PATIENT: 58-year-old male
ADMISSION DATE: [10 days ago]
DISCHARGE DATE: [Today]
LENGTH OF STAY: 10 days

PRINCIPAL DIAGNOSIS:
1. Acute perforated appendicitis

SECONDARY DIAGNOSES:
2. Surgical site infection (SSI) - superficial incisional, right lower quadrant McBurney incision
3. Type 2 diabetes mellitus
4. Hypertension
5. Obesity

PROCEDURES:
1. Laparoscopic appendectomy converted to open appendectomy [10 days ago]
2. Bedside wound opening and debridement for SSI [5 days ago]
3. Negative pressure wound therapy (wound vac) placement [3 days ago]

HOSPITAL COURSE:

APPENDICITIS:
The patient presented with 3 days of right lower quadrant pain and was found to have perforated appendicitis with localized peritonitis on CT scan. He underwent laparoscopic appendectomy which was converted to open due to extensive inflammation. A McBurney incision was used. The peritoneal cavity was irrigated and a JP drain was placed. He was started on piperacillin-tazobactam for peritonitis coverage.

SURGICAL SITE INFECTION:
On post-operative day 5, the patient developed fever, increasing WBC, and signs of wound infection including erythema, purulent drainage, and early dehiscence of the McBurney incision. CT scan confirmed a superficial fluid collection without deeper abscess. Wound cultures grew methicillin-susceptible Staphylococcus aureus (MSSA) and Escherichia coli.

The wound was opened at bedside for drainage and packed with wet-to-dry dressings. Vancomycin was added empirically and later discontinued when cultures showed MSSA. Infectious Disease was consulted for antibiotic management. On POD 7, negative pressure wound therapy (wound vac) was initiated to promote wound healing.

The patient responded well to treatment. By POD 10, he was afebrile with normalized WBC and a clean, granulating wound. He was transitioned to oral cephalexin and is being discharged with home wound vac therapy.

RELEVANT CULTURES:
Wound culture: MSSA (oxacillin sensitive), E. coli (ceftriaxone sensitive)
Blood cultures: No growth

DISCHARGE MEDICATIONS:
1. Cephalexin 500mg PO four times daily x 4 more days (then discontinue)
2. Oxycodone 5mg PO every 6 hours as needed for pain (Qty #16)
3. Docusate 100mg PO twice daily while taking oxycodone
4. Lisinopril 10mg PO daily (home medication)
5. Metformin 1000mg PO twice daily (home medication - resume)

WOUND STATUS AT DISCHARGE:
- RLQ McBurney incision: Open, 4.5 x 2.0 x 2.5 cm, healing by secondary intention
- Wound bed: 85% healthy granulation tissue
- No signs of active infection
- Wound vac in place at -125 mmHg with good seal
- Estimated time to full granulation: 1-2 weeks

DISCHARGE DISPOSITION: Home with services

HOME HEALTH SERVICES:
- Wound vac dressing changes Monday, Wednesday, Friday
- Wound assessment at each visit
- Report concerns to surgery clinic

DURABLE MEDICAL EQUIPMENT:
- Portable wound vac unit with supplies for 2 weeks
- Contact information for DME company provided

FOLLOW-UP APPOINTMENTS:
1. Surgery clinic - Dr. Peterson, 1 week (wound vac check, possible discontinuation)
2. Primary care - 2 weeks (diabetes follow-up)
3. No Infectious Disease follow-up needed unless complications

DISCHARGE INSTRUCTIONS:
1. WOUND VAC CARE:
   - Keep wound vac on at all times except brief bathroom breaks
   - Ensure seal is maintained (no air leaks)
   - Charge battery when connected to outlet
   - Do not shower with wound vac; sponge baths only
   - Home health will change dressings 3x weekly

2. ACTIVITY:
   - No lifting more than 10 pounds for 4 weeks
   - No driving while taking opioid pain medication
   - Walking encouraged, gradually increase activity

3. DIET:
   - Regular diet, high protein for wound healing
   - Good hydration

4. RETURN TO EMERGENCY DEPARTMENT IF:
   - Temperature > 101°F
   - Severe abdominal pain
   - Wound vac alarms that cannot be resolved
   - Bright red bleeding from wound
   - Foul-smelling wound drainage
   - Increasing redness around wound

PROGNOSIS:
Good. Expect complete wound healing with continued wound vac therapy. Low risk of recurrence after appendectomy.

_____________________
Dr. James Peterson, MD, FACS
General Surgery

cc: Primary Care Physician
    Home Health Agency
"""
        },
        {
            "note_type": "nursing_note",
            "content": """NURSING DOCUMENTATION - WOUND ASSESSMENT

Date/Time: 1400
Patient: 58-year-old male, POD 8 from appendectomy with surgical site infection

VITAL SIGNS:
T: 98.6F HR: 80 BP: 130/78 RR: 16 SpO2: 98% RA

WOUND VAC ASSESSMENT:

Seal Integrity: Intact, no air leaks heard
Pressure Setting: -125 mmHg continuous (as ordered)
Canister Status: 50% full, serosanguinous drainage, no odor
Tubing: Patent, no kinks or clogs
Foam Appearance (visible through drape): Compressed appropriately, indicating good seal

DRESSING STATUS:
Last changed: Yesterday at 1000 by wound care nurse
Next change due: Tomorrow
Drape: Intact, adherent to periwound skin
No drainage around edges

PATIENT COMFORT:
Pain level: 3/10 at rest, 5/10 with position changes
Pain medication: Patient using oral oxycodone PRN, last dose 0800
Reports wound vac is "tolerable" and he is getting used to it

PATIENT ACTIVITY:
- Ambulating independently with wound vac unit
- Able to manage tubing safely
- Uses rolling IV pole to carry wound vac when walking
- No falls

WOUND VAC EDUCATION REVIEW:
Prior to discharge, reviewed with patient and wife:
[X] How to clamp tubing for bathroom
[X] How to respond to alarms (check seal, check tubing)
[X] When to call for help (persistent alarms, bright red blood, fever)
[X] Importance of keeping charged
[X] Not to adjust settings
[X] How to empty canister (demonstrated by nursing, but home health will do)
[X] Sponge bath only, no shower

Both patient and wife demonstrated understanding and ability to troubleshoot basic issues.

NUTRITION:
Diet: Regular, high protein
Intake: Good appetite, eating >75% of meals
Supplements: Protein shake with meals per nutrition recommendations
Prealbumin level ordered to assess nutritional status for wound healing

BLOOD GLUCOSE MONITORING:
0700: 142 mg/dL
1200: 168 mg/dL
Glucose control adequate on home metformin regimen (restarted POD 8)

ANTIBIOTIC ADMINISTRATION:
Cephalexin 500mg PO given at 0800, 1200 (next dose 1800, 2400)
No signs of adverse reaction
Patient tolerating without GI upset

DISCHARGE READINESS ASSESSMENT:
[X] Wound vac education complete
[X] Patient demonstrates safe handling of wound vac
[X] Home health arranged (confirmed)
[X] DME arranged (wound vac unit and supplies confirmed)
[X] Prescription for oral antibiotics provided
[X] Follow-up appointment scheduled
[X] Discharge instructions reviewed and provided

Patient and wife verbalize readiness for discharge and confidence in managing wound vac at home. They have 24-hour contact information for surgery clinic, home health, and DME company.

_____________________
Maria Gonzalez, RN, BSN
"""
        },
    ]

    # Notes WITHOUT CLABSI-relevant keywords (should be filtered out)
    IRRELEVANT_NOTES = [
        {
            "note_type": "progress_note",
            "content": """CARDIOLOGY CONSULT

Reason for Consult: Preoperative cardiac risk assessment

HISTORY OF PRESENT ILLNESS:
This is a 68-year-old female with history of hypertension, hyperlipidemia, and type 2 diabetes who is scheduled for elective right total knee arthroplasty. She is being evaluated for cardiac clearance prior to surgery.

The patient denies chest pain, shortness of breath, orthopnea, paroxysmal nocturnal dyspnea, or lower extremity edema. She reports good exercise tolerance - able to climb 2 flights of stairs and walk several blocks without symptoms. No history of myocardial infarction, coronary artery disease, heart failure, or arrhythmias. No prior cardiac testing.

PAST MEDICAL HISTORY:
1. Hypertension x 15 years, well-controlled
2. Hyperlipidemia
3. Type 2 diabetes mellitus - on metformin, A1c 7.2%
4. Osteoarthritis
5. Obesity (BMI 32)

MEDICATIONS:
1. Lisinopril 20mg daily
2. Amlodipine 5mg daily
3. Atorvastatin 40mg daily
4. Metformin 1000mg BID
5. Aspirin 81mg daily

PHYSICAL EXAMINATION:
Blood pressure: 138/82 mmHg, Heart rate: 72 bpm regular
JVP: Not elevated
Heart: Regular rate and rhythm, normal S1/S2, no murmurs, rubs, or gallops
Lungs: Clear to auscultation bilaterally
Extremities: No peripheral edema, 2+ peripheral pulses

ELECTROCARDIOGRAM:
Normal sinus rhythm, rate 70. Normal axis. No ST-T wave changes. No prior ECG for comparison.

ASSESSMENT AND RECOMMENDATIONS:
1. Low cardiac risk for non-cardiac surgery
- Revised Cardiac Risk Index: 1 point (diabetes) = Low risk (< 1% MACE)
- Patient has good functional capacity (> 4 METs)
- No active cardiac conditions

2. Recommendations for surgery:
- Patient is cleared for elective orthopedic surgery from cardiac standpoint
- Continue home medications including aspirin and statin perioperatively
- Hold ACE inhibitor morning of surgery, resume postoperatively when euvolemic
- Hold metformin day of surgery and 48 hours post if IV contrast planned
- Standard DVT prophylaxis per surgical protocol

3. No further cardiac testing indicated at this time

Thank you for this interesting consult. We will be happy to see the patient again if any cardiac concerns arise postoperatively.

_____________________
Dr. Robert Kim, MD, FACC
Cardiology
"""
        },
        {
            "note_type": "progress_note",
            "content": """ORTHOPEDIC SURGERY POST-OPERATIVE NOTE

PROCEDURE: Right total knee arthroplasty
DATE OF SURGERY: Yesterday
SURGEON: Dr. Thompson

POST-OPERATIVE DAY 1

SUBJECTIVE:
Patient reports moderate pain at surgical site, currently 5/10, improved from 8/10 immediately post-op. Pain is well-controlled with current regimen. She was able to get out of bed to chair with PT assistance this morning. No chest pain, shortness of breath, or calf pain. No nausea or vomiting. Tolerating clear liquid diet, will advance as tolerated.

OBJECTIVE:
Vitals: T 99.1F, HR 84, BP 142/88, RR 16, SpO2 96% RA
General: Alert, oriented, comfortable
Right knee: Dressing clean, dry, intact. Moderate swelling expected post-operatively. Knee immobilizer in place. Able to perform straight leg raise with minimal assistance. Sensation intact to light touch in all dermatomes. Pedal pulses 2+ bilaterally. Calf soft, non-tender. No erythema or warmth of calf.

Labs:
Hemoglobin: 10.2 (pre-op 12.8) - expected post-operative drop
Platelets: 185
Creatinine: 0.9

ASSESSMENT/PLAN:
68-year-old female POD 1 from right TKA, doing well.

1. Post-operative pain - well controlled
- Continue PCA for today, transition to oral pain medication tomorrow
- Ice and elevation

2. DVT prophylaxis
- Enoxaparin 40mg SQ daily started this morning
- SCDs while in bed
- Early mobilization

3. Physical therapy
- PT/OT to see daily
- Weight bearing as tolerated with walker
- Goal: 90 degrees flexion, full extension by discharge

4. Anemia - expected post-operative
- Monitor hemoglobin daily
- Transfuse if Hgb < 7 or symptomatic

5. Diabetes
- Sliding scale insulin while NPO
- Resume metformin once eating and creatinine stable

6. Disposition
- Anticipate discharge to acute rehab in 2-3 days
- Case management consulted

_____________________
Dr. Thompson, MD
Orthopedic Surgery
"""
        },
        {
            "note_type": "nursing_note",
            "content": """NURSING SHIFT DOCUMENTATION - DAY SHIFT (0700-1900)

PATIENT: 72-year-old male admitted for COPD exacerbation

VITAL SIGNS:
0800: T 98.4, HR 88, BP 136/82, RR 20, SpO2 92% on 2L NC
1200: T 98.6, HR 84, BP 128/78, RR 18, SpO2 94% on 2L NC
1600: T 98.2, HR 80, BP 132/80, RR 18, SpO2 95% on 2L NC

RESPIRATORY ASSESSMENT:
Breath sounds diminished bilaterally with scattered expiratory wheezes. Using accessory muscles mildly. Productive cough with white sputum. Incentive spirometry performed hourly while awake, achieving 1000mL (goal 1500mL). Oxygen weaned from 4L to 2L NC with saturations maintained above 92%.

ACTIVITY:
Ambulated to bathroom x3 with minimal assistance. Walked 50 feet in hallway with rolling walker and portable O2. Tolerated activity without significant desaturation (lowest SpO2 91% with recovery to 94% within 1 minute of rest).

MEDICATIONS ADMINISTERED:
- Prednisone 40mg PO at 0800
- Albuterol/ipratropium nebulizer at 0800, 1200, 1600
- Azithromycin 250mg PO at 0900
- Enoxaparin 40mg SQ at 0900
- Home medications continued as ordered

NUTRITION:
Regular diet. Ate 75% breakfast, 50% lunch. Encouraged fluid intake. PO intake approximately 1200mL. No nausea or vomiting.

INTAKE/OUTPUT:
Intake: PO 1200mL, IV 500mL (maintenance fluids)
Output: Urine 1400mL via urinal

PATIENT EDUCATION:
- Reviewed proper inhaler technique with patient
- Discussed importance of smoking cessation (patient quit 2 years ago)
- Reviewed signs of respiratory distress to report
- Patient demonstrated understanding

FALL RISK: Moderate (Morse score 45)
- Fall precautions in place
- Bed alarm on
- Call light within reach
- Non-skid socks provided

SKIN: Intact, no pressure injuries identified. Braden score 18.

PLAN FOR EVENING SHIFT:
- Continue respiratory treatments q4h
- Encourage ambulation
- Monitor for improvement in symptoms
- May consider room air trial tomorrow if continues to improve

_____________________
Michelle Parker, RN, BSN
"""
        },
        {
            "note_type": "progress_note",
            "content": """PULMONOLOGY CONSULTATION

Reason for Consult: COPD exacerbation, steroid management

HISTORY OF PRESENT ILLNESS:
This is a 72-year-old male with history of severe COPD (GOLD stage III, FEV1 38% predicted on last PFTs 6 months ago) who presents with 4 days of increased dyspnea, productive cough with yellow-green sputum, and decreased exercise tolerance. He was unable to walk from bedroom to bathroom without becoming severely short of breath, whereas at baseline he can walk approximately one block on flat ground.

He denies fever, chest pain, hemoptysis, or lower extremity swelling. No recent travel or sick contacts. He has had 2 COPD exacerbations requiring hospitalization in the past year, most recently 4 months ago.

PAST MEDICAL HISTORY:
1. COPD - severe, GOLD stage III
   - 45 pack-year smoking history, quit 2 years ago
   - Home O2 2L NC with exertion (not continuous)
   - Last PFT: FEV1 38% predicted, FEV1/FVC 42%
2. Hypertension
3. Osteoporosis - on alendronate
4. Benign prostatic hyperplasia
5. Remote history of peptic ulcer disease

CURRENT HOME MEDICATIONS:
1. Tiotropium 18mcg inhaled daily
2. Budesonide/formoterol 160/4.5 mcg 2 puffs BID
3. Albuterol HFA PRN
4. Lisinopril 10mg daily
5. Alendronate 70mg weekly
6. Tamsulosin 0.4mg daily

PHYSICAL EXAMINATION:
Vitals: T 98.8F, HR 92, BP 144/88, RR 22, SpO2 91% on 2L NC
General: Comfortable at rest, speaks in full sentences
HEENT: No JVD
Chest: Barrel-shaped, decreased breath sounds bilaterally, expiratory wheezes diffusely, no crackles
Heart: Regular, no murmurs
Extremities: No edema
Skin: No cyanosis

DIAGNOSTIC DATA:
Chest X-ray: Hyperinflation, flattened diaphragms consistent with COPD. No focal consolidation or effusion.
ABG (on 2L NC): pH 7.38, pCO2 52, pO2 68, HCO3 30 (chronic compensated respiratory acidosis, baseline)
WBC: 11.2 with 80% neutrophils

ASSESSMENT AND RECOMMENDATIONS:

1. COPD exacerbation - likely infectious trigger
- Continue systemic corticosteroids: prednisone 40mg daily x 5 days total
- Continue antibiotic (azithromycin 250mg x 5 days)
- Scheduled nebulized bronchodilators q4h
- Wean oxygen as tolerated, goal SpO2 88-92%
- No indication for BiPAP at this time given adequate ventilation

2. Prevention of future exacerbations
- Current inhaler regimen appropriate (LAMA + ICS/LABA)
- Confirm influenza and pneumococcal vaccines up to date
- Will arrange outpatient pulmonary rehabilitation referral
- Consider adding roflumilast if frequent exacerbations continue

3. Osteoporosis prophylaxis
- Already on alendronate, which is appropriate given steroid use
- Calcium and vitamin D supplementation recommended

4. Smoking cessation
- Congratulate patient on 2 years tobacco-free
- Encourage continued abstinence

Anticipated discharge in 2-3 days if continues to improve. Will arrange pulmonary follow-up in 2-3 weeks.

_____________________
Dr. Lisa Patel, MD
Pulmonary Medicine
"""
        },
        {
            "note_type": "progress_note",
            "content": """NEPHROLOGY CONSULTATION

Reason for Consult: Acute kidney injury

HISTORY OF PRESENT ILLNESS:
This is a 65-year-old female with history of hypertension and type 2 diabetes who was admitted 3 days ago for elective cholecystectomy. She is now post-operative day 2. The surgical team noted a rise in creatinine from baseline 1.0 to current 2.4 mg/dL and requested nephrology evaluation.

The patient underwent uncomplicated laparoscopic cholecystectomy. She received standard perioperative IV fluids. She was hypotensive intraoperatively (BP 85/50) for approximately 20 minutes, which responded to fluid bolus. No pressors were required. She received ketorolac 30mg x1 in PACU for pain control. She has had good urine output post-operatively (averaging 60-80 mL/hr).

She denies flank pain, hematuria, dysuria, or decreased urine output. No foamy urine. She has been taking her home medications including lisinopril and metformin until the day of surgery.

PAST MEDICAL HISTORY:
1. Hypertension
2. Type 2 diabetes mellitus (A1c 7.8%)
3. Cholelithiasis - now s/p cholecystectomy
4. Obesity (BMI 34)

MEDICATIONS:
Pre-admission: Lisinopril 20mg daily, metformin 1000mg BID, atorvastatin 20mg daily
Current: Lisinopril held, metformin held, IV fluids, pain medications

PHYSICAL EXAMINATION:
Vitals: T 98.4F, HR 78, BP 128/76, RR 14
General: Comfortable, no distress
Cardiovascular: Regular rate and rhythm, no murmurs
Lungs: Clear bilaterally
Abdomen: Soft, laparoscopic port sites clean, mild tenderness
Extremities: No edema

LABORATORY DATA:
Creatinine trend:
- Baseline (1 month ago): 1.0 mg/dL
- Admission (pre-op): 1.0 mg/dL
- POD 1: 1.6 mg/dL
- POD 2 (today): 2.4 mg/dL

BUN: 38 mg/dL
Potassium: 4.8 mEq/L
Urinalysis: Specific gravity 1.025, no protein, no blood, no casts
FeNa: 0.4% (pre-renal pattern)

RENAL ULTRASOUND: Normal sized kidneys bilaterally, no hydronephrosis, no stones.

ASSESSMENT AND PLAN:

1. Acute Kidney Injury - KDIGO Stage 2 (creatinine 2-2.9x baseline)
Etiology: Most likely multifactorial pre-renal AKI
- Intraoperative hypotension (ATN component possible)
- NSAID exposure (ketorolac)
- ACE inhibitor (held appropriately but may have contributed)

Recommendations:
a) Continue holding nephrotoxins (NSAIDs, ACE inhibitor)
b) Ensure adequate hydration - NS at 100 mL/hr, reassess volume status
c) Avoid IV contrast if possible
d) Trend creatinine daily
e) Expect improvement over next 48-72 hours with supportive care
f) If creatinine continues to rise or oliguria develops, consider further workup

2. Hyperkalemia risk
- Potassium 4.8, monitor closely
- Avoid potassium-sparing drugs and potassium supplementation
- Low potassium diet

3. Diabetes management
- Continue holding metformin until creatinine improves
- Sliding scale insulin for glycemic control

4. Hypertension
- Continue holding ACE inhibitor
- BP currently well-controlled without it
- Resume lisinopril once creatinine at baseline

Prognosis for renal recovery is excellent given reversible causes and prompt recognition. Will continue to follow daily. Please call with any concerns or if renal function worsens.

_____________________
Dr. James Wong, MD
Nephrology
"""
        },
        {
            "note_type": "nursing_note",
            "content": """NURSING DOCUMENTATION - NIGHT SHIFT (1900-0700)

PATIENT: 58-year-old female, post-op day 3 hip replacement

VITAL SIGNS OVERNIGHT:
2000: T 98.6, HR 76, BP 128/74, RR 16, SpO2 97% RA
0000: T 98.4, HR 72, BP 122/70, RR 14, SpO2 98% RA
0400: T 98.8, HR 74, BP 126/72, RR 16, SpO2 97% RA

PAIN MANAGEMENT:
Patient reports pain 4/10 at rest, 6/10 with movement at start of shift. Administered:
- Oxycodone 5mg PO at 2100 - pain decreased to 3/10
- Oxycodone 5mg PO at 0300 - pain 4/10, patient able to sleep
Patient using PCA appropriately for breakthrough pain. Ice pack applied to surgical site with good effect.

SURGICAL SITE:
Right hip incision - dressing clean, dry, intact. No drainage noted on dressing. Hemovac drain in place, output 30mL serosanguinous fluid this shift (within expected range). Patient denies numbness or tingling in right foot. Pedal pulses palpable, capillary refill < 2 seconds. Able to wiggle toes.

MOBILITY:
Patient transferred from bed to bedside commode x2 with assistance of 1. Using walker. Weight bearing as tolerated per orthopedic orders. Hip precautions maintained (no flexion > 90 degrees, no crossing legs, no internal rotation). Abduction pillow in place while in bed.

SLEEP:
Patient slept intermittently, approximately 5 hours total. Awoke for pain medication and bathroom. Declined sleep medication.

DVT PROPHYLAXIS:
- Enoxaparin 40mg SQ administered at 2100
- SCDs in place and functioning when in bed
- Patient encouraged to perform ankle pumps hourly while awake

INTAKE/OUTPUT:
Intake: PO 600mL, IV 250mL (hep-lock, occasional flush)
Output: Urine 750mL (voiding independently), Hemovac 30mL

MEDICATIONS ADMINISTERED:
- Scheduled: Enoxaparin, stool softener, home medications
- PRN: Oxycodone x2, ondansetron x1 for mild nausea

PATIENT CONCERNS:
Patient expressed anxiety about discharge planning. Reassured that case management is working on skilled nursing placement per her preference. Social work to see today.

PLAN FOR DAY SHIFT:
- PT/OT to see for continued mobility training
- Dressing change due today per surgery
- Continue DVT prophylaxis
- Advance diet as tolerated
- Update on discharge planning

_____________________
Andrea Thompson, RN, BSN
"""
        },
        {
            "note_type": "progress_note",
            "content": """ENDOCRINOLOGY CONSULTATION

Reason for Consult: Inpatient diabetes management

HISTORY OF PRESENT ILLNESS:
This is a 62-year-old male with long-standing type 2 diabetes mellitus who was admitted 2 days ago for community-acquired pneumonia. His blood glucose levels have been poorly controlled during this hospitalization, ranging from 180-350 mg/dL despite sliding scale insulin.

At home, he takes metformin 1000mg BID and glipizide 10mg BID. His last A1c was 9.2% three months ago. He has diabetic complications including peripheral neuropathy and background retinopathy. He denies any DKA or hypoglycemic episodes.

PAST MEDICAL HISTORY:
1. Type 2 diabetes mellitus x 15 years
   - Peripheral neuropathy
   - Background diabetic retinopathy
   - No nephropathy (last microalbumin normal)
2. Hypertension
3. Hyperlipidemia
4. Obesity (BMI 33)
5. OSA on CPAP

CURRENT MEDICATIONS:
- Metformin 1000mg BID (HELD - acute illness)
- Glipizide 10mg BID (HELD)
- Insulin sliding scale
- Lisinopril 20mg daily
- Atorvastatin 40mg daily
- Aspirin 81mg daily

HOME MEDICATIONS NOT YET RESTARTED:
- Metformin, glipizide as above

LABORATORY DATA:
Glucose trend: 285, 340, 220, 310, 180, 350 (over past 48 hours)
A1c: 9.2% (3 months ago)
Creatinine: 1.0 (baseline)
Potassium: 4.2

PHYSICAL EXAMINATION:
General: Obese male, comfortable, on room air
Vitals: BP 138/82, HR 80, T 99.0F (improving from 101.5F on admission)
Skin: No diabetic dermopathy, no foot ulcers
Feet: Monofilament sensation diminished bilaterally (known neuropathy)
Remainder of exam unremarkable

ASSESSMENT AND RECOMMENDATIONS:

1. Type 2 Diabetes Mellitus - Uncontrolled during hospitalization
This is expected stress hyperglycemia in the setting of acute pneumonia. His home regimen (metformin + sulfonylurea) is not appropriate for inpatient management.

Recommendations:
a) Discontinue sliding scale only regimen
b) Initiate basal-bolus insulin:
   - Lantus (glargine) 20 units at bedtime
   - Humalog (lispro) 6 units before meals
   - Correctional scale before meals and at bedtime
c) Target glucose 140-180 mg/dL (ADA inpatient guidelines)
d) Check fingerstick glucose AC and HS

2. Home regimen adjustment at discharge:
- A1c 9.2% suggests need for intensification regardless of this admission
- Options: Add basal insulin to current regimen OR switch to basal-bolus
- Will reassess glycemic control during admission and make discharge recommendations
- Diabetes education consult placed for self-management training

3. Hypoglycemia prevention:
- Ensure meal trays are delivered with insulin administration
- If NPO, hold mealtime insulin, reduce basal by 20%

4. Long-term complications:
- Remind to follow up with ophthalmology annually
- Foot exam today: no ulcers, protective sensation diminished
- Consider referral to podiatry after discharge

We will continue to follow and adjust insulin as needed. Please call with any concerns or if patient becomes NPO.

_____________________
Dr. Michelle Sanders, MD
Endocrinology
"""
        },
        {
            "note_type": "progress_note",
            "content": """PHYSICAL THERAPY INITIAL EVALUATION

PATIENT: 70-year-old female
DIAGNOSIS: Left hip ORIF for intertrochanteric fracture
PRECAUTIONS: Posterior hip precautions, weight bearing as tolerated

SUBJECTIVE:
Patient is POD 2 from left hip ORIF following a fall at home. She reports left hip pain 5/10 at rest, 7/10 with movement. She denies dizziness, numbness, or tingling in the left lower extremity. Prior to admission, patient was independent in all mobility and ADLs, living alone in a single-story home. She used no assistive device. She is motivated to participate in therapy and return home.

PAST MEDICAL HISTORY:
- Osteoporosis (likely contributed to fracture)
- Hypertension
- Hypothyroidism
- No prior surgeries or falls

OBJECTIVE:

Bed Mobility:
- Rolling: Moderate assistance x1
- Supine to sit: Moderate assistance x1
- Log roll technique for hip precautions

Transfers:
- Sit to stand: Moderate assistance x1 with front wheeled walker
- Bed to chair: Moderate assistance x1
- Maintained hip precautions throughout

Gait:
- Ambulated 25 feet with front wheeled walker
- Moderate assistance x1 for safety and cueing
- Gait pattern: Antalgic, decreased stance time on left
- Weight bearing as tolerated - patient hesitant to bear full weight

Balance:
- Sitting: Good static, fair dynamic
- Standing: Fair static, poor dynamic

Strength (left lower extremity):
- Hip flexion: 3/5 (limited by pain)
- Knee extension: 4/5
- Ankle dorsiflexion: 4+/5

Range of Motion (left hip):
- Limited by pain and surgical precautions
- Active ROM not formally assessed POD 2

ASSESSMENT:
70-year-old female POD 2 L hip ORIF with impaired mobility, transfers, gait, and balance. Patient demonstrates good potential for functional improvement with skilled physical therapy. Current functional status requires discharge to skilled nursing facility or acute rehabilitation for intensive therapy.

GOALS (2-week time frame):
1. Bed mobility: Modified independent with log roll technique
2. Transfers: Supervision with front wheeled walker
3. Ambulation: 150 feet with front wheeled walker, supervision level
4. Stairs: 4 steps with rail, minimal assistance (if returning home)

PLAN:
- PT 1-2x daily during acute stay
- Focus on transfers, gait training, balance, strengthening
- Reinforce hip precautions with all activities
- Recommend discharge to skilled nursing facility for continued rehabilitation
- Outpatient PT following SNF discharge

_____________________
Sarah Mitchell, PT, DPT
"""
        },
        {
            "note_type": "progress_note",
            "content": """GASTROENTEROLOGY CONSULTATION

Reason for Consult: Elevated liver enzymes, possible drug-induced liver injury

HISTORY OF PRESENT ILLNESS:
This is a 55-year-old male who was admitted 5 days ago for sepsis secondary to cellulitis of the right lower extremity. He has been treated with vancomycin and piperacillin-tazobactam. On routine labs today, he was found to have newly elevated liver transaminases:
- AST: 245 U/L (normal < 40, admission 32)
- ALT: 312 U/L (normal < 40, admission 28)
- Alkaline phosphatase: 95 U/L (normal)
- Total bilirubin: 1.2 mg/dL (normal)

The patient denies right upper quadrant pain, nausea, vomiting, jaundice, clay-colored stools, or dark urine. He has no history of liver disease, hepatitis, or alcohol abuse. He denies any herbal supplements or acetaminophen use.

PAST MEDICAL HISTORY:
1. Cellulitis (current admission)
2. Type 2 diabetes mellitus
3. Hypertension
4. Hyperlipidemia
5. No known liver disease

MEDICATIONS:
Current:
- Vancomycin (day 5)
- Piperacillin-tazobactam (day 5)
- Metformin (held)
- Lisinopril
- Atorvastatin (home medication, continued)

PHYSICAL EXAMINATION:
Vitals: Afebrile, stable
General: Comfortable, no jaundice
Abdomen: Soft, non-tender, no hepatomegaly, no Murphy's sign
Skin: Right lower extremity cellulitis improving, no jaundice

LABORATORY DATA:
Hepatitis serologies: Pending
INR: 1.0
Albumin: 3.8

Right upper quadrant ultrasound: Normal liver echogenicity, no biliary dilation, gallbladder normal, no ascites.

ASSESSMENT AND RECOMMENDATIONS:

1. Elevated Liver Enzymes - Hepatocellular Pattern
Differential diagnosis:
a) Drug-induced liver injury (most likely)
   - Piperacillin-tazobactam: Known hepatotoxin
   - Atorvastatin: Can cause transaminitis, but patient on this chronically
b) Sepsis-related hypoperfusion (less likely given timing)
c) Viral hepatitis (pending serologies)
d) Ischemic hepatitis (less likely, no hypotension)

Recommendations:
1. Check hepatitis A, B, C serologies (sent)
2. Consider switching piperacillin-tazobactam to alternative antibiotic
   - Discuss with ID regarding options for cellulitis coverage
3. Continue atorvastatin - unlikely culprit given chronic use, but can hold if enzymes continue to rise
4. Trend LFTs every 48 hours
5. If enzymes > 10x ULN or bilirubin rises significantly, recommend stopping all potentially hepatotoxic medications

2. Prognosis:
If drug-induced, expect improvement within 1-2 weeks after offending agent discontinued. Isolated transaminitis with normal bilirubin and INR suggests low risk of acute liver failure.

Will continue to follow. Please call with hepatitis serologies or if clinical change.

_____________________
Dr. Kevin Patel, MD
Gastroenterology
"""
        },
        {
            "note_type": "nursing_note",
            "content": """NURSING ASSESSMENT - ADMISSION

Date/Time: 1430
Patient: 78-year-old male
Admitting Diagnosis: Congestive heart failure exacerbation

ALLERGIES: Penicillin (anaphylaxis), Sulfa (rash)

VITAL SIGNS:
T: 98.2F  HR: 92  BP: 168/95  RR: 24  SpO2: 88% RA -> 94% on 4L NC
Weight: 92 kg (dry weight per patient: 85 kg)

CHIEF COMPLAINT:
"I can't breathe when I lie down and my legs are really swollen"

HISTORY:
Patient reports progressive shortness of breath over past week, now with orthopnea requiring 4 pillows to sleep. He has noticed significant bilateral lower extremity swelling and weight gain of 7 kg over 2 weeks. He has dietary indiscretion (ate several salty meals at restaurants) and admits to not taking his furosemide regularly. No chest pain, palpitations, or syncope.

PAST MEDICAL HISTORY:
- Heart failure with reduced ejection fraction (EF 30% on last echo)
- Coronary artery disease s/p CABG 2015
- Atrial fibrillation on anticoagulation
- Chronic kidney disease stage 3
- Hypertension
- Type 2 diabetes

HOME MEDICATIONS (per patient):
- Furosemide 40mg twice daily (admits taking only once daily)
- Lisinopril 20mg daily
- Carvedilol 25mg twice daily
- Warfarin 5mg daily
- Metformin 500mg twice daily
- Aspirin 81mg daily

PHYSICAL ASSESSMENT:

Neurological: Alert and oriented x4. Pupils equal and reactive. No focal deficits.

Respiratory: Labored at rest on room air, improved on 4L NC. Crackles bilateral bases to mid-lung fields. Using accessory muscles. Speaks in short sentences due to dyspnea.

Cardiovascular: Irregularly irregular rhythm (known Afib). S1, S2 present, S3 gallop noted. JVD to angle of jaw at 45 degrees. No murmurs appreciated.

Gastrointestinal: Abdomen distended, soft, non-tender. Bowel sounds present. Hepatomegaly noted on palpation.

Genitourinary: Foley not in place. Has not voided since arrival. Will monitor output closely.

Extremities: 3+ pitting edema bilateral lower extremities to knees. Skin intact, no wounds.

Skin: Intact. No pressure injuries. Braden score 16 (mild risk).

INTERVENTIONS:
- Oxygen via nasal cannula at 4L/min
- IV access x2 (18g right forearm, 20g left hand)
- Labs drawn (BMP, CBC, BNP, troponin, INR)
- Chest X-ray completed at bedside
- Telemetry monitoring initiated
- Strict I&O
- Daily weights ordered
- Low sodium diet ordered
- Foley catheter inserted per order for accurate output monitoring

PSYCHOSOCIAL:
Patient lives with wife who is present at bedside. Both aware of diagnosis and plan for diuresis. Patient expresses guilt about medication non-adherence. Encouraged and reassured. Social work consulted for discharge planning.

SAFETY:
- Fall risk: High (Morse score 55)
- Bed alarm activated
- Call light in reach
- Non-skid socks provided

PLAN:
- Admit to telemetry unit
- IV furosemide diuresis per cardiology
- Fluid restriction 1.5L/day
- Monitor respiratory status closely
- Assess response to diuresis

_____________________
Patricia Collins, RN, BSN
"""
        },
        {
            "note_type": "progress_note",
            "content": """PSYCHIATRY CONSULTATION

Reason for Consult: Depression, capacity evaluation

IDENTIFYING INFORMATION:
This is a 68-year-old female with history of major depressive disorder, currently admitted for COPD exacerbation. The primary team requests psychiatric evaluation for depressed mood and assessment of decision-making capacity regarding her expressed wish to leave against medical advice.

HISTORY OF PRESENT ILLNESS:
Per chart review and interview, the patient has a long history of recurrent major depression, previously treated with sertraline with good response. She discontinued her antidepressant 6 months ago when she "felt better" and did not follow up with her psychiatrist. Over the past 2 months, she has experienced worsening depressed mood, anhedonia, poor sleep, decreased appetite with 10 lb weight loss, low energy, and passive suicidal ideation ("I wouldn't mind if I didn't wake up") without plan or intent.

She was admitted 3 days ago for COPD exacerbation. She has been frustrated with the hospitalization and today stated she wants to leave AMA. When asked why, she says "What's the point? I'm just going to get sick again anyway." She denies active suicidal ideation or intent. She has no history of suicide attempts.

PSYCHIATRIC HISTORY:
- Major depressive disorder, recurrent, first episode age 45
- No prior psychiatric hospitalizations
- No history of mania or psychosis
- No substance use disorder

MEDICATIONS:
- Previously: Sertraline 100mg daily (discontinued 6 months ago)
- Current: None for psychiatric indications

MENTAL STATUS EXAMINATION:
Appearance: Elderly female, appears stated age, fair hygiene, in hospital gown
Behavior: Cooperative but mildly irritable, poor eye contact
Speech: Normal rate and rhythm, low volume
Mood: "Terrible"
Affect: Constricted, sad, tearful at times
Thought process: Linear, goal-directed
Thought content: Passive SI ("don't care if I live or die"), no HI, no delusions
Perceptions: No hallucinations
Cognition: Alert and oriented x4, attention intact
Insight: Limited
Judgment: Impaired by depression

CAPACITY ASSESSMENT:
The patient was evaluated for decision-making capacity regarding leaving AMA:
1. Understanding: She can articulate her diagnosis and that the medical team recommends continuing treatment
2. Appreciation: Limited - she minimizes the seriousness of leaving while still requiring oxygen and steroids
3. Reasoning: Impaired by depression - her reasoning is influenced by hopelessness and nihilistic thoughts
4. Expression of choice: She can express a consistent choice to leave

ASSESSMENT:
1. Major Depressive Disorder, Recurrent, Severe, without psychotic features
The patient meets criteria for major depression with passive suicidal ideation. Her depressive symptoms are significantly impairing her judgment regarding medical care.

2. Decision-making capacity: Impaired
While she meets criteria for understanding and expressing a choice, her appreciation and reasoning are impaired by her depressive illness. She is unable to adequately weigh the risks and benefits due to hopelessness and nihilism.

RECOMMENDATIONS:
1. The patient lacks decision-making capacity for the AMA decision at this time due to severe depression
2. Recommend restarting sertraline 50mg daily, increase to 100mg in 1 week if tolerated
3. 1:1 observation is NOT indicated - no acute safety concerns
4. Suicide precautions per nursing protocol
5. If patient continues to request AMA, recommend ethics consultation
6. Consider family meeting to discuss goals of care
7. Will follow daily during hospitalization
8. Outpatient psychiatry follow-up arranged for 1 week post-discharge

_____________________
Dr. Rebecca Foster, MD
Consultation-Liaison Psychiatry
"""
        },
    ]

    def __init__(self, hai_type: str = "clabsi", include_irrelevant: bool = True, num_irrelevant: int = 22):
        """Initialize mock note source.

        Args:
            hai_type: Type of HAI to generate notes for ("clabsi", "ssi", or "cdi")
            include_irrelevant: Whether to include irrelevant notes for filtering test
            num_irrelevant: Number of irrelevant notes to include
        """
        self.hai_type = hai_type.lower()
        self.include_irrelevant = include_irrelevant
        self.num_irrelevant = min(num_irrelevant, len(self.IRRELEVANT_NOTES))

    def get_notes_for_patient(
        self,
        patient_id: str,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        note_types: list[str] | None = None,
    ) -> list[ClinicalNote]:
        """Generate mock clinical notes.

        Creates realistic-length notes (2-3K chars each): 8 relevant + up to 22 irrelevant.

        Args:
            patient_id: Patient identifier
            start_date: Start of date range
            end_date: End of date range
            note_types: Types of notes to include

        Returns:
            List of ClinicalNote objects
        """
        notes = []
        base_date = end_date or datetime.now()

        # Select relevant notes based on HAI type
        if self.hai_type == "ssi":
            relevant_notes = self.SSI_RELEVANT_NOTES
        else:
            relevant_notes = self.CLABSI_RELEVANT_NOTES

        # Add all relevant notes
        for i, note_data in enumerate(relevant_notes):
            note_date = base_date - timedelta(days=i % 7, hours=i * 3)
            notes.append(ClinicalNote(
                id=f"note-relevant-{i}",
                patient_id=patient_id,
                note_type=note_data["note_type"],
                date=note_date,
                content=note_data["content"],
                source="mock",
                author=f"Dr. Demo{i}",
            ))

        # Add irrelevant notes if requested
        if self.include_irrelevant:
            for i, note_data in enumerate(self.IRRELEVANT_NOTES[:self.num_irrelevant]):
                note_date = base_date - timedelta(days=i % 7, hours=i * 2 + 1)
                notes.append(ClinicalNote(
                    id=f"note-irrelevant-{i}",
                    patient_id=patient_id,
                    note_type=note_data["note_type"],
                    date=note_date,
                    content=note_data["content"],
                    source="mock",
                    author=f"Dr. Other{i}",
                ))

        # Sort by date descending
        notes.sort(key=lambda n: n.date, reverse=True)

        return notes
