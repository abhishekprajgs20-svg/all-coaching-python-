# -*- coding: utf-8 -*-
"""Coaching PDF to TXT formatter (desktop GUI). Requires Python 3.10+ and PyMuPDF."""
import os, re, sys, traceback
from pathlib import Path
try:
    import pymupdf as fitz
except ImportError:
    try: import fitz
    except ImportError: fitz=None

ZW=re.compile(r'[\u200b\ufeff\u200c\u200d\u2060\ufeff\u00ad]')
DEV=re.compile(r'[\u0900-\u097f]')
JUNK=re.compile(r'(www\.|https?://|copyright|visionias\.in|do not open this test booklet|maximum marks|time allowed|immediately after the commencement|answer sheet|answers sheet|does not have any unprinted|unprinted or turn or missing pages|encode clearly the test booklet|enter your roll number on the test booklet|this test booklet contains|all items carry equal marks|attempt all items|total marks will depend|penalty for wrong answers|sheet for rough work|prepared by|subscribe our channel|telegram channel|whatsapp on|difficulty:\s|source:\s|subject:\s|topic:\s|subtopic:\s|PNP\s*2026|PRELIMS\s*NAVIGATOR\s*PROGRAM|Full\s*Length\s*Test|Sarrthi\s*IAS|Sarthi\s*IAS\s*class\s*notes)',re.I)
Q_RE=re.compile(r'^\s*(?:Q\s*\.?\s*)?(\d{1,3})\s*[\.\):\-]\s*(.*)$',re.I)
ANS_INLINE=re.compile(r'^\s*(?:Ans(?:wer)?|Correct Answer)\s*[:\-)]*\s*\(?\s*([a-e1-5])\s*\)?',re.I)
EXPL_RE=re.compile(r'^\s*(?:Exp(?:lanation)?|Solution)\s*[:\-)]*\s*(.*)$',re.I)
OPT_RE=re.compile(r'^\s*\(\s*([a-e])\s*\)\s*(.*)$|^\s*([a-e])\s*[.)]\s*(.*)$',re.I)
OPT_RE2=re.compile(r'^\s*\(([1-5])\)\s*(.*)$')

def norm(s):
    s=ZW.sub(' ',s).replace('\xa0',' ').replace('\x07',' ')
    # Replace all unicode whitespace / separators with normal space so words do not glue
    s=re.sub(r'[\u2000-\u200f\u2028-\u202f\u205f\u2060\ufeff\u00ad]+',' ',s)
    s=re.sub(r'[ \t]+',' ',s).strip()
    return s

def clean_frag(s):
    """Remove residual page headers / page numbers that leak into options or explanations."""
    s = norm(s)
    s = re.sub(r'(?i)\b(?:PNP\s*2026|PRELIMS\s*NAVIGATOR\s*PROGRAM|Full\s*Length\s*Test\s*[-–]?\s*\d+|Sarrthi\s*IAS|Sarthi\s*IAS)\b','',s)
    s = re.sub(r'\s+\d{1,2}\s*$','',s)          # trailing lone page number
    s = re.sub(r'^\s*\d{1,2}\s+','',s)          # leading lone page number
    # Residual answer-line fragments that sometimes leak into explanation start
    s = re.sub(r'(?i)^\s*(?:and\s+)?(?:Both\s+)?Statement-?[II1-2]*\s+(?:and\s+Statement-?[II1-2]*\s+)?(?:are\s+correct\s+and\s+)?(?:is|are)\s+the\s+correct\s+explanation[^.]*\.\s*','',s)
    s = re.sub(r'(?i)^\s*(?:and\s+)?Statement-?[II1-2]*\s+is\s+the\s+correct\s+explanation[^.]*\.\s*','',s)
    s = re.sub(r'(?i)^\s*correct\s+','',s)
    s = re.sub(r'(?i)^\s*and\s+Statement','Statement',s)
    return norm(s)

def get_lines(path):
    doc=fitz.open(path); lines=[]
    for pn,page in enumerate(doc):
        raw=[]
        for b in page.get_text('dict').get('blocks',[]):
            if b.get('type')!=0: continue
            for ln in b.get('lines',[]):
                txt=norm(''.join(sp.get('text','') for sp in ln.get('spans',[])))
                if not txt: continue
                x0,y0,x1,y1=ln['bbox']
                if JUNK.search(txt): continue
                raw.append((x0,y0,x1,y1,txt,pn))
        # Prefer normal reading order (top-to-bottom) for single-column pages.
        # Only switch to left-column then right-column order when the page clearly
        # has two populated text columns with little horizontal overlap.
        mid=page.rect.width/2
        left=[r for r in raw if (r[0]+r[2])/2 < mid]
        right=[r for r in raw if (r[0]+r[2])/2 >= mid]
        def overlap_ratio(a,b):
            inter=max(0,min(a[2],b[2])-max(a[0],b[0]))
            return inter/max(1,min(a[2]-a[0],b[2]-b[0]))
        cross_pairs=0
        for a in left[:120]:
            for b in right[:120]:
                if abs(a[1]-b[1])<4 and overlap_ratio(a,b)>0.15:
                    cross_pairs+=1
        clear_two_col=(len(left)>=8 and len(right)>=8 and cross_pairs<3 and
                       max((r[2] for r in left),default=0) < page.rect.width*0.78 and
                       min((r[0] for r in right),default=page.rect.width) > page.rect.width*0.38)
        # Vision IAS test booklets are almost always strict two-column; force column order
        # when both sides have reasonable content even if a few cross-pairs exist.
        vision_two_col = (len(left)>=6 and len(right)>=6 and
                          max((r[2] for r in left),default=0) < page.rect.width*0.55 and
                          min((r[0] for r in right),default=page.rect.width) > page.rect.width*0.45)
        if clear_two_col or vision_two_col:
            ordered=sorted(left,key=lambda r:(r[1],r[0]))+sorted(right,key=lambda r:(r[1],r[0]))
        else:
            ordered=sorted(raw,key=lambda r:(round(r[1]/3)*3,r[0]))
        # If question numbers on a page are out of order because two columns were interleaved
        # (notably Vision IAS pages containing Q98/Q99 in the left column and Q100 in the right),
        # restore column-major reading order only when the page clearly has separated columns.
        qnums=[]
        for r in ordered:
            mm=re.match(r'^\s*(\d{1,3})\s*[.)](?:\s+.*)?$',r[4])
            if mm: qnums.append(int(mm.group(1)))
        if len(qnums)>=3 and qnums != sorted(qnums):
            left=[r for r in ordered if r[0] < page.rect.width*0.50]
            right=[r for r in ordered if r[0] >= page.rect.width*0.50]
            if left and right:
                ordered=sorted(left,key=lambda r:(r[1],r[0]))+sorted(right,key=lambda r:(r[1],r[0]))
        lines.extend(ordered)
    doc.close()
    return [r[4] for r in lines]

def english_only(s):
    s=norm(s)
    # For bilingual PDFs (esp. Sarthi): drop the entire line if it contains Devanagari.
    # This ensures only pure English content is kept.
    if DEV.search(s):
        return ''
    return norm(s)

def preserve_structure(s):
    """Keep question stems readable: statement labels, enumerated items, tables and final prompts on separate lines."""
    s=ZW.sub('',s).replace('\xa0',' ').replace('\u200b',' ')
    # Normalize whitespace but retain explicit line boundaries already recovered from the PDF.
    s=s.replace('\r','\n')
    s=re.sub(r'[ \t]+',' ',s)
    # Remove coaching branding/watermarks accidentally interleaved with content.
    s=re.sub(r'(?i)\b(?:VISION\s*IAS|VISIONIAS|VAJIRAM\s*&\s*RAVI|VAJIRAM\s*AND\s*RAVI|NEXT\s*IAS|PW\s*ONLY\s*IAS|FORUM\s*IAS|SARTHI\s*IAS|SARATHI\s*IAS)\b','',s)
    # Split final interrogative prompt phrases even if extraction glued them to preceding text.
    prompts = [
      r'Which\s+one\s+of\s+the\s+following\s+is\s+correct\s+in\s+respect\s+of\s+the\s+above\s+statements\??',
      r'Which\s+of\s+the\s+statements?\s+(?:given\s+above\s+)?(?:is/are|are|is)\s+correct\??',
      r'Which\s+of\s+the\s+following\s+statements?\s+(?:is/are|are|is)\s+correct\??',
      r'How\s+many\s+of\s+(?:the\s+)?(?:above|following|these|given\s+above)\b[^?]*\?',
      r'How\s+many\s+of\s+the\s+following\b[^?]*\?',
      r'How\s+many\s+of\s+the\s+statements?\s+(?:given\s+above|above)\b[^?]*\?',
      r'How\s+many\s+statements?\b[^?]*\?',
      r'How\s+many\s+of\s+the\s+above\b[^?]*\?',
      r'In\s+which\s+of\s+the\s+above\s+rows?\s+is\s+the\s+given\s+information\s+correctly\s+matched\??',
      r'Which\s+of\s+the\s+following\s+pairs?\s+(?:is/are|are|is)\s+correctly\s+matched\??',
      r'Which\s+of\s+the\s+above\s+is/are\s+correct\??',
      r'Which\s+of\s+the\s+following\s+(?:is|are)\s+correct\??',
      r'Which\s+one\s+of\s+the\s+following\b[^?]*\?',
      r'Which\s+of\s+the\s+following\b[^?]*\?',
      r'Which\s+among\s+the\s+above\b[^?]*\?',
      r'Choose\s+the\s+correct\s+(?:answer|option|code)\b[^?]*\??',
      r'Select\s+the\s+correct\s+answer\b[^?]*\??',
      r'Identify\s+the\s+correct\s+answer\b[^?]*\??',
      r'Which\s+statement\s+given\s+above\s+is\s+correct\??',
      r'Which\s+of\s+the\s+following\s+is\s+the\s+correct\s+(?:order|sequence|code)\??',
      r'With\s+reference\s+to\s+the\s+above\b[^?]*\?',
      r'Select\s+the\s+correct\s+statement\(s\)\s+using\s+the\s+code\s+given\s+below\s*:',
      r'Select\s+the\s+correct\s+answer\s+using\s+the\s+code\s+given\s+below\s*:',
      r'Select\s+the\s+correct\s+answer\s+from\s+the\s+codes\s+given\s+below\s*:',
    ]
    for pat in prompts:
        s=re.sub(r'(?i)\s*(?='+pat+r')','\n',s)
    # Statement-I/II, Statement 1/2 and their Roman numeral variants. Tolerate missing trailing punct.
    s=re.sub(r'(?i)(?:(?<=[:.;\n])|^)\s*(?=Statement\s*[-–—]?\s*(?:I{1,3}|IV|V|VI{0,3}|[1-9][0-9]*)\b)','\n',s)
    # Headings for two-list / matching questions.
    s=re.sub(r'(?i)\s*(?=(?:Consider|Examine|Study)\s+the\s+following\s+(?:statements?|pairs?|lists?|items?|information)\s*:)','\n',s)
    s=re.sub(r'(?i)\s*(?=(?:Match\s+List\s*[-–]?\s*[I12]|List\s*[-–]?\s*[I12]|Column\s+[I12]|List\s+[A-B])\b)','\n',s)
    # Sarthi-style section headers inside explanations
    s=re.sub(r'(?i)\s*(?=Additional\s+Dimensions?\b)','\n',s)
    s=re.sub(r'(?i)\s*(?=Trick\s+to\s+Remember\b)','\n',s)
    s=re.sub(r'(?i)\s*(?=Source\s*:)','\n',s)
    s=re.sub(r'(?i)\s*(?=Difficulty\s*:)','\n',s)
    # Numbered items such as 1. / 2. / 3. and (1), split when followed by a plausible list entry.
    # Avoid option labels (a)-(e), decimals and numbers embedded in prose.
    s=re.sub(r'(?<=[.:;])\s*(?=(?:\(?\d{1,2}[.)]\)?)[ \t]+(?=[A-Z(“\'"‘]))','\n',s)
    s=re.sub(r'\s+(?=(?:\(?\d{1,2}[.)]\)?)[ \t]+[A-Z(“\'"‘])','\n',s)
    # Also after sentence end for common PDF line-glue of lists.
    s=re.sub(r'(?<=[.!?])\s*(?=\d{1,2}[.)]\s+[A-Za-z(“\'"])','\n',s)
    # Roman-numbered entries: I., II., (i), (ii), etc. More tolerant of spacing.
    s=re.sub(r'(?i)\s+(?=(?:\(?\s*(?:iv|iii|ii|i|v|vi|vii|viii|ix|x)\s*[.)]\)?)[ \t]+[A-Z(“\'"‘])','\n',s)
    s=re.sub(r'(?i)(?<=[:;])\s*(?=(?:\(?\s*(?:iv|iii|ii|i|v|vi|vii|viii|ix|x)\s*[.)]\)?)[ \t]+[A-Z(“\'"])','\n',s)
    # Lettered list items a), b), c) / a. b. only when clearly part of a stem/list (not answer options).
    s=re.sub(r'(?i)(?<=:)\s*(?=[a-d][.)]\s+[A-Z(])','\n',s)
    s=re.sub(r'(?i)\s+(?=[a-d][.)]\s+[A-Z(“\'"][a-z])','\n',s)
    # Clean residual coaching fragments.
    s=re.sub(r'(?i)\s*(?:VISION\s*IAS|VAJIRAM\s*(?:&|AND)\s*RAVI|NEXT\s*IAS|SARTHI\s*IAS)\s*',' ',s)
    # Remove accidental duplicate spaces and blank lines, retain one item per line.
    out=[]
    for line in s.splitlines():
        line=norm(line)
        if line: out.append(line)
    return '\n'.join(out)


def qstart(line):
    m=Q_RE.match(line)
    if not m:return None
    n=int(m.group(1)); rest=m.group(2).strip()
    # Avoid treating numbered statements and explanation list entries as Q starts
    if line.strip().lower().startswith('statement'): return None
    return n,rest

def parse_inline_pdf(path, coach):
    """SFG/Sarthi: question, options, answer and explanation all in one PDF."""
    lines=get_lines(path); qs=[]; cur=None; state='stem'; expected=1
    for raw in lines:
        t=english_only(raw)
        if not t: continue
        # Sarthi uses Q1. and SFG uses Q.1)
        qm=re.match(r'^\s*Q\s*\.?\s*(\d{1,3})\s*[\).:]?\s*(.*)$',t,re.I)
        if qm:
            n=int(qm.group(1))
            if n==expected or (cur is None and n>=1):
                if cur: qs.append(cur)
                cur={'num':n,'stem':[],'opts':{},'answer':None,'exp':[]}
                expected=n+1; state='stem'
                if qm.group(2).strip(): cur['stem'].append(qm.group(2).strip())
                continue
        if cur is None: continue
        # answer and explanation markers
        am=ANS_INLINE.match(t)
        if am and (t.lower().startswith(('ans','answer','correct answer'))):
            cur['answer']=am.group(1).lower(); state='after_answer'; continue
        em=EXPL_RE.match(t)
        if em:
            state='exp'
            if em.group(1): cur['exp'].append(em.group(1))
            continue
        # Sarthi answer format: Answer: a) I and III only
        if re.match(r'^Answer\s*:',t,re.I):
            m=re.match(r'^Answer\s*:\s*\(?([a-e])\)?[.)]?\s*(.*)$',t,re.I)
            if m:
                cur['answer']=m.group(1).lower()
                if m.group(2).strip(): cur['answer_text']=m.group(2).strip()
                state='after_answer'; continue
        # Some bilingual PDFs place English option labels after a column/order break;
        # recover clear a)-d) options even if the previous line accidentally entered explanation state.
        om=OPT_RE.match(t)
        if om and len(cur['opts']) < 4:
            key=(om.group(1) or om.group(3)).lower(); val=(om.group(2) if om.group(1) else om.group(4)).strip()
            if key in 'abcd':
                cur['opts'][key]=clean_frag(val)
                state='opts'
                continue
        if state=='exp':
            if not re.match(r'^(source|difficulty|subject|topic|subtopic)\s*:',t,re.I):
                cur['exp'].append(clean_frag(t))
            continue
        om=OPT_RE.match(t)
        if om:
            key=(om.group(1) or om.group(3)).lower(); val=(om.group(2) if om.group(1) else om.group(4)).strip()
            if key in 'abcde':
                cur['opts'][key]=clean_frag(cur['opts'].get(key,'')+' '+val)
                state='opts'; continue
        if state=='opts' and cur['opts']:
            k=list(cur['opts'])[-1]; cur['opts'][k]=norm(cur['opts'][k]+' '+t)
        elif state in ('stem','after_answer'):
            if state=='after_answer':
                # SFG sometimes has Exp marker on the next line; other text before Exp is likely explanation
                cur['exp'].append(clean_frag(t)); state='exp'
            else: cur['stem'].append(t)
    if cur: qs.append(cur)
    # avoid duplicated extraction artifacts only when both number and full stem match
    return qs

def looks_like_instruction(t):
    low=t.lower()
    phrases=(
      'test booklet contains', 'the test paper contains', 'each item comprises four responses', 'immediately after the commencement', 'maximum marks', 'time allowed',
      'you should check that this test booklet', 'enter your roll number', 'encode clearly',
      'there are four alternatives for the answer', 'choose only one response', 'all the questions',
      'penalty for wrong answer', 'for each question for which a wrong answer',
      'do not open this test booklet', 'before attempting paper', 'instructions for the candidates',
      'read the following instructions', 'this booklet contains', 'rough work',
    )
    return any(x in low for x in phrases)

def parse_test_questions(path, coach):
    lines=get_lines(path); qs=[]; cur=None; state='stem'; expected=None
    for raw in lines:
        t=english_only(raw)
        if not t: continue
        if looks_like_instruction(t):
            continue
        # Some Next IAS pages extract a question number as bare digits (e.g. '63')
        # because the punctuation sits in a separate PDF text span. Only accept it when
        # it is exactly the next expected question and the previous question's options began.
        bare_num=re.match(r'^\s*(\d{1,3})\s*$',t)
        if bare_num and cur is not None and state=='opts' and expected is not None and int(bare_num.group(1))==expected:
            if cur: qs.append(cur)
            cur={'num':int(bare_num.group(1)),'stem':[],'opts':{},'answer':None,'exp':[]}
            expected=int(bare_num.group(1))+1; state='stem'
            continue
        m=re.match(r'^\s*(\d{1,3})\s*[.)]\s*(.*)$',t)
        # Many PDFs place the question number on a line by itself (e.g. "1.") and
        # the stem on following lines. Start a question there, but only at the start
        # of a document or after the previous question's options have begun.
        if m and not m.group(2).strip():
            n=int(m.group(1))
            if (cur is None and n == 1) or (cur is not None and n == expected and state == 'opts'):
                if cur: qs.append(cur)
                cur={'num':n,'stem':[],'opts':{},'answer':None,'exp':[]}
                expected=n+1; state='stem'
                continue
        if coach == 'Vision IAS' and cur is None and m:
            low=m.group(2).lower()
            if any(x in low for x in ('booklet','roll number','unprinted','answer sheet','marks','penalty','rough work','choose only one','four alternatives','series a, b, c or d')):
                continue
        # A new top-level question begins only after the previous question has reached its options.
        # This prevents statement 1/2/3 and match-list numbering from becoming fake questions.
        if m:
            n=int(m.group(1)); rest=m.group(2).strip()
            # Guard against numbered list items (1. 2. 3.) inside a question stem being treated as new questions.
            # Real question stems after the number usually start with "Consider", "Which", "With reference", etc.
            # Apply the strict "looks like real Q" check mainly for Vision (two-column list items).
            looks_like_real_q = bool(re.match(
                r'(?i)^(?:Consider|Which|With\s+reference|How\s+many|Match|In\s+the\s+context|'
                r'The\s+\w+|Recently|According|Examine|Study|Identify|Select|Choose|What|Who|Where|When|Why|'
                r'What\s+does|What\s+is|What\s+are|Under|Among|Regarding)',
                rest or ''))
            if coach == 'Vision IAS':
                is_start = (cur is None and n==1) or (cur is not None and (
                    (n==expected and state=='opts' and (looks_like_real_q or not rest)) or 
                    (rest and n>cur['num'] and state in ('opts','stem') and looks_like_real_q)
                ))
            else:
                is_start = (cur is None and n==1) or (cur is not None and (
                    (n==expected and state=='opts') or 
                    (coach in ('Next IAS','Vajiram') and rest and n>cur['num'] and state in ('opts','stem'))
                ))
            if is_start:
                if cur: qs.append(cur)
                cur={'num':n,'stem':[],'opts':{},'answer':None,'exp':[]}
                expected=n+1; state='stem'
                if rest: cur['stem'].append(rest)
                continue
        if cur is None: continue
        om=OPT_RE.match(t)
        if om:
            key=(om.group(1) or om.group(3)).lower(); val=(om.group(2) if om.group(1) else om.group(4)).strip()
            cur['opts'][key]=val; state='opts'; continue
        if state=='opts' and cur['opts']:
            k=list(cur['opts'])[-1]; cur['opts'][k]=norm(cur['opts'][k]+' '+t)
        else:
            cur['stem'].append(t)
    if cur: qs.append(cur)
    # question PDFs must not accidentally include instruction pages as questions
    return qs

def parse_solution(path, coach):
    """Page-aware solution parser. Skips answer-key pages and captures explanations until the next question.

    Coaching PDFs commonly put answer keys in tables and explanations on later pages; parsing
    the entire PDF as one undifferentiated stream loses continuation pages and answer markers.
    """
    doc=fitz.open(path)
    pages=[]
    for page in doc:
        raw=page.get_text('text') or ''
        # Keep physical page boundaries; these matter for answer-key vs explanation pages.
        pages.append(raw)
    doc.close()
    answers={}; explanations={}
    current=None; buf=[]; in_explanation=False; awaiting_answer=False

    def save():
        nonlocal buf, current, in_explanation
        if current is not None and buf:
            text=preserve_structure(' '.join(buf))
            if text:
                # Continuation pages for a question should append rather than overwrite.
                explanations[current]=norm((explanations.get(current,'')+' '+text).strip())
        buf=[]; in_explanation=False

    def start_question(n, answer=None):
        nonlocal current, buf, in_explanation, awaiting_answer
        save()
        current=n; awaiting_answer=answer is None
        if answer:
            answers[n]=answer.lower(); awaiting_answer=False

    # Match actual explanation-page headers; do not treat enumerated statements in prose as headers.
    q_header=re.compile(r'^\s*(?:Q\s*)?(\d{1,3})\s*[.)]?\s*(?:(?:Ans(?:wer)?\s*:\s*)?\(?([a-eA-E])\)?)?\s*$',re.I)
    vision_header=re.compile(r'^\s*Q\s*(\d{1,3})\s*[.)]?\s*([A-Ea-e])\s*$',re.I)
    answer_line=re.compile(r'^\s*(?:Ans(?:wer)?|Correct\s+Answer)\s*:\s*\(?([a-e])\)?\s*$',re.I)
    exp_line=re.compile(r'^\s*(?:Exp(?:lanation)?|Solution)\s*:\s*(.*)$',re.I)

    for page_index, rawpage in enumerate(pages):
        rawlines=[norm(x) for x in rawpage.splitlines()]
        rawlines=[x for x in rawlines if x]
        page_join=' '.join(rawlines).lower()
        # Answer key pages should only contribute keys, never be counted as explanation pages.
        key_page=('answer key' in page_join and len(re.findall(r'\b\d{1,3}\.\s*\(?[a-e]\)?',page_join))>=10)
        if key_page:
            for line in rawlines:
                m=re.match(r'^\s*(\d{1,3})\s*[.)]\s*\(?([a-e])\)?\s*$',line,re.I)
                if m: answers[int(m.group(1))]=m.group(2).lower()
                # compact rows may have multiple entries in a single extracted line
                for mm in re.finditer(r'(?<!\d)(\d{1,3})\s*[.)]\s*\(([a-e])\)',line,re.I):
                    answers[int(mm.group(1))]=mm.group(2).lower()
            # If the same page also contains explanation headers (common in Vajiram),
            # do not skip the rest of the page; continue normal processing below.
            if not any(re.match(r'^\s*(?:Q\s*)?\d{1,3}\s*[.)]?\s*$', ln, re.I) or
                       re.match(r'^\s*Q\s*\d{1,3}\s*[.)]?\s*[A-Ea-e]\s*$', ln, re.I) or
                       re.match(r'^\s*Answer\s*:', ln, re.I) for ln in rawlines):
                continue
        # Avoid cover/instruction pages unless they contain recognizable question headings.
        for idx,line in enumerate(rawlines):
            if re.search(r'(?i)\b(?:VISION\s*IAS|NEXT\s*IAS|VAJIRAM\s*&\s*RAVI|PW\s*ONLY\s*IAS|SARTHI\s*IAS)\b',line) and len(line)<80:
                continue
            vm=vision_header.match(line)
            if vm:
                start_question(int(vm.group(1)),vm.group(2)); in_explanation=True
                continue
            # Common header forms: "1.", "1. (c)", "Q1.", "Q1. (c)".
            # Strong question boundary: a numbered header with an inline answer, or a bare
            # question number immediately followed by an answer marker/answer letter. This avoids
            # mistaking numbered statements inside an explanation for a new question.
            inline = re.match(r'^\s*(?:Q\s*)?(\d{1,3})\s*[.)]\s*(?:Ans(?:wer)?\s*:\s*)?\(?([a-e])\)?\s*$',line,re.I)
            if inline:
                n=int(inline.group(1)); ans=inline.group(2)
                if 1 <= n <= 200:
                    start_question(n,ans); continue
            bare = re.match(r'^\s*(?:Q\s*)?(\d{1,3})\s*[.)]?\s*$',line,re.I)
            if bare:
                n=int(bare.group(1)); look=rawlines[idx+1:idx+4]
                next_is_answer=any(answer_line.match(x) or re.match(r'^\(?[a-e]\)?$',x,re.I) for x in look[:2])
                next_is_exp=any(re.match(r'(?i)^(?:Exp(?:lanation)?|Solution)\s*:',x) for x in look[:3])
                # Require an answer marker nearby. This is the key guard against numbered list items.
                if next_is_answer or (next_is_exp and coach in ('PW','Sarthi IAS','Vajiram','Vision IAS')):
                    next_answer=next((answer_line.match(x).group(1) for x in look if answer_line.match(x)),None)
                    if not next_answer:
                        next_answer=next((re.sub(r'[^a-e]','',x.lower()) for x in look[:2] if re.match(r'^\(?[a-e]\)?$',x,re.I)),None)
                    start_question(n,next_answer); continue
            am=answer_line.match(line)
            if am and current is not None:
                answers[current]=am.group(1).lower(); awaiting_answer=False
                continue
            # Next IAS uses a standalone answer letter directly below the question number.
            if current is not None and awaiting_answer and re.match(r'^\(?[a-e]\)?$',line,re.I):
                answers[current]=re.sub(r'[^a-e]','',line.lower()); awaiting_answer=False
                continue
            em=exp_line.match(line)
            if em and current is not None:
                in_explanation=True
                if em.group(1): buf.append(em.group(1))
                continue
            if current is not None:
                # Next IAS uses bullets without an explicit Exp: marker; start collecting after answer.
                if coach=='Next IAS' and not in_explanation and not awaiting_answer and (line.startswith(('●','•','o ','♦')) or len(line)>35):
                    in_explanation=True
                # PW / Sarthi / Vajiram usually have explicit Exp; continuation text after it is retained.
                if in_explanation:
                    if re.match(r'(?i)^(?:source|subject|topic|subtopic|difficulty)\s*:',line):
                        continue
                    # Vision SOL text layer is sparse and often concatenates multiple Qs.
                    # Stop collecting once we see a clear end-of-explanation phrase and already have content.
                    if coach == 'Vision IAS' and buf and re.search(
                        r'(?i)(?:hence,?\s+option\s*\(?[a-d]\)?|therefore,?\s+option\s*\(?[a-d]\)?|'
                        r'hence,?\s+(?:statement|pair|both)\s|option\s*\(?[a-d]\)?\s+is\s+the\s+correct)',
                        line):
                        buf.append(line)
                        save()
                        current = None
                        continue
                    buf.append(line)
    save()
    return answers, {k: preserve_structure(v) for k,v in explanations.items()}

def fmt(q, answer=None, explanation=None):
    n=q['num']; stem=preserve_structure(' '.join(q.get('stem',[])))
    opts=q.get('opts',{})
    ans=(q.get('answer') or answer or '').lower()
    if ans and ans.isdigit(): ans=chr(96+int(ans))
    exp=preserve_structure(' '.join(q.get('exp',[]))) or preserve_structure(explanation or '')
    out=[f"Q{n}. {stem}".strip(),'😂']
    for k in 'abcde':
        if k in opts:
            val=preserve_structure(clean_frag(opts[k]))
            out.append(val+(' ✅' if ans==k else ''))
    out.append('Ex: '+(exp if exp else '[REVIEW: explanation not found in source PDF]'))
    return '\n'.join(out)

def code_key(path):
    """Normalize filename by removing role words while retaining test identifiers and series labels."""
    stem=Path(path).stem.lower()
    stem=re.sub(r'[^a-z0-9]+',' ',stem)
    stem=re.sub(r'\b(?:test|tests|sol|solution|solutions|answer|answers|key|booklet|question|paper)\b',' ',stem)
    stem=re.sub(r'\s+',' ',stem).strip()
    return stem

def process_coaching(coach, test_paths, sol_paths):
    outputs=[]; reports=[]
    single=coach in ('SFG','Sarthi IAS')
    solmaps={}
    if not single:
        for sp in sol_paths:
            key=code_key(sp); solmaps.setdefault(key,[]).append(sp)
    for tp in test_paths:
        try:
            if single:
                qs=parse_inline_pdf(tp,coach)
                ans={q['num']:q.get('answer') for q in qs}
                ex={}
            else:
                qs=parse_test_questions(tp,coach)
                key=code_key(tp)
                candidates=solmaps.get(key,[])
                if not candidates and len(test_paths)==len(sol_paths):
                    candidates=[sol_paths[test_paths.index(tp)]]
                if candidates:
                    ans,ex=parse_solution(candidates[0],coach)
                else:
                    ans,ex={},{}
                    reports.append(f"{Path(tp).name}: matching solution PDF not found")
            blocks=[]; warnings=[]
            for q in qs:
                n=q['num']; answer=q.get('answer') or ans.get(n); explanation=' '.join(q.get('exp',[])) or ex.get(n,'')
                if not q.get('stem'): warnings.append(f"Q{n}: question text missing")
                if len(q.get('opts',{}))<4: warnings.append(f"Q{n}: only {len(q.get('opts',{}))} options recognised")
                if not answer: warnings.append(f"Q{n}: answer not matched")
                if not explanation: warnings.append(f"Q{n}: explanation not matched")
                blocks.append(fmt(q,answer,explanation))
            outpath=os.path.splitext(tp)[0]+'_formatted.txt'
            with open(outpath,'w',encoding='utf-8') as f:f.write('\n\n'.join(blocks)+'\n')
            outputs.append(outpath)
            reports.append(f"{Path(tp).name}: {len(qs)} questions -> {Path(outpath).name}")
            if not qs: reports.append(f"  CRITICAL: no questions detected; check the source layout.")
            nums=[q.get('num') for q in qs]
            if nums and nums != list(range(nums[0], nums[0]+len(nums))): reports.append(f"  WARNING: question numbering has gaps/duplicates: {nums[:12]} ...")
            if len(qs) < 10: reports.append(f"  WARNING: unusually few questions detected; inspect output before use.")
            reports.extend(f"  WARNING {Path(tp).name}: {w}" for w in warnings)
        except Exception as e:
            reports.append(f"ERROR {Path(tp).name}: {e}")
    # Save a persistent audit report beside the first selected test PDF, so the user
    # can identify extraction gaps instead of mistaking a generated TXT for verified output.
    if test_paths:
        try:
            report_path=os.path.join(os.path.dirname(test_paths[0]), 'coaching_txt_validation_report.txt')
            with open(report_path,'w',encoding='utf-8') as rf:
                rf.write('COACHING PDF → TXT VALIDATION REPORT\n')
                rf.write('This report flags suspicious extraction; it does NOT certify correctness.\n\n')
                rf.write('Selected coaching: '+coach+'\n\n')
                rf.write('\n'.join(reports))
                rf.write('\n\nManual review is required for every warning, complex table, scanned page, and answer/explanation alignment.\n')
            reports.append(f'Validation report saved: {report_path}')
        except Exception as e:
            reports.append(f'Could not save validation report: {e}')
    return outputs,reports

