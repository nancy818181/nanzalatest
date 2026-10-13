"""2.9.109: English employee details written in Arabic for the official forms (R3, CNSS ...).

Known Lebanese / Arabic names, places, nationalities and job words are taken from the lists below; any other word is
transliterated letter by letter. The result is a proposal: Saber writes it in the Arabic box and the user corrects it
there when needed (a corrected box is never overwritten)."""
from __future__ import annotations

import re

NAMES = {
    # first names - men
    "mohamad": "محمد", "mohammad": "محمد", "mohammed": "محمد", "muhammad": "محمد", "mohamed": "محمد", "ahmad": "أحمد", "ahmed": "أحمد",
    "mahmoud": "محمود", "moustafa": "مصطفى", "mostafa": "مصطفى", "mustafa": "مصطفى", "ali": "علي", "hassan": "حسن", "hasan": "حسن",
    "hussein": "حسين", "houssein": "حسين", "hussain": "حسين", "khaled": "خالد", "khalil": "خليل", "omar": "عمر", "omer": "عمر",
    "youssef": "يوسف", "yousef": "يوسف", "joseph": "جوزيف", "georges": "جورج", "george": "جورج", "elie": "إيلي", "elias": "الياس",
    "charbel": "شربل", "tony": "طوني", "antoine": "أنطوان", "pierre": "بيار", "paul": "بول", "michel": "ميشال", "marc": "مارك",
    "fadi": "فادي", "rami": "رامي", "sami": "سامي", "samir": "سمير", "nabil": "نبيل", "walid": "وليد", "ziad": "زياد", "ziyad": "زياد",
    "bassam": "بسام", "fouad": "فؤاد", "fuad": "فؤاد", "rabih": "ربيع", "rabie": "ربيع", "jihad": "جهاد", "imad": "عماد", "emad": "عماد",
    "ibrahim": "إبراهيم", "brahim": "إبراهيم", "ismail": "إسماعيل", "issa": "عيسى", "jamal": "جمال", "kamal": "كمال", "karim": "كريم",
    "kareem": "كريم", "majed": "ماجد", "maher": "ماهر", "marwan": "مروان", "nader": "نادر", "nasser": "ناصر", "nizar": "نزار", "raed": "رائد",
    "rabee": "ربيع", "saad": "سعد", "said": "سعيد", "saeed": "سعيد", "salim": "سليم", "salem": "سالم", "tarek": "طارق", "tarik": "طارق",
    "wael": "وائل", "wassim": "وسيم", "wissam": "وسام", "yasser": "ياسر", "yehia": "يحيى", "yahya": "يحيى", "zein": "زين", "zaher": "زاهر",
    "abbas": "عباس", "abdallah": "عبدالله", "abdullah": "عبدالله", "abdel": "عبد", "adnan": "عدنان", "amin": "أمين", "anwar": "أنور",
    "ayman": "أيمن", "bilal": "بلال", "chadi": "شادي", "shadi": "شادي", "chafic": "شفيق", "chawki": "شوقي", "fares": "فارس", "fawzi": "فوزي",
    "ghassan": "غسان", "habib": "حبيب", "hadi": "هادي", "hani": "هاني", "haytham": "هيثم", "hisham": "هشام", "hicham": "هشام",
    "jad": "جاد", "jaafar": "جعفر", "jalal": "جلال", "jean": "جان", "joe": "جو", "kassem": "قاسم", "qassem": "قاسم", "louay": "لؤي",
    "mazen": "مازن", "mounir": "منير", "mouhamad": "محمد", "moussa": "موسى", "nadim": "نديم", "naji": "ناجي", "nassim": "نسيم",
    "oussama": "أسامة", "osama": "أسامة", "rachid": "رشيد", "rashid": "رشيد", "riad": "رياض", "riyad": "رياض", "roger": "روجيه",
    "salah": "صلاح", "toufic": "توفيق", "tawfik": "توفيق", "wajdi": "وجدي", "zakaria": "زكريا", "hamza": "حمزة", "hamze": "حمزة",
    "abed": "عابد", "akram": "أكرم", "assaad": "أسعد", "asaad": "أسعد", "badih": "بديع", "camille": "كميل", "edmond": "إدمون",
    "farid": "فريد", "fouad.": "فؤاد", "hayssam": "هيثم", "houssam": "حسام", "hussam": "حسام", "ihab": "إيهاب", "joumana": "جمانة",
    # first names - women
    "fatima": "فاطمة", "fatmeh": "فاطمة", "fatme": "فاطمة", "zeinab": "زينب", "zainab": "زينب", "mariam": "مريم", "maryam": "مريم",
    "maria": "ماريا", "mary": "ماري", "marie": "ماري", "rita": "ريتا", "nadia": "نادية", "nadine": "نادين", "hilene": "هيلين",
    "hélène": "هيلين", "helene": "هيلين", "layla": "ليلى", "leila": "ليلى", "laila": "ليلى", "rana": "رنا", "rima": "ريما", "reem": "ريم",
    "rim": "ريم", "sara": "سارة", "sarah": "سارة", "hiba": "هبة", "heba": "هبة", "dana": "دانا", "lina": "لينا", "lama": "لمى",
    "maya": "مايا", "mira": "ميرا", "nour": "نور", "noor": "نور", "nancy": "نانسي", "joelle": "جويل", "carla": "كارلا", "christine": "كريستين",
    "grace": "غريس", "hala": "هالة", "hanan": "حنان", "houda": "هدى", "huda": "هدى", "iman": "إيمان", "jana": "جنى", "jamila": "جميلة",
    "khadija": "خديجة", "khadijeh": "خديجة", "lamia": "لمياء", "manal": "منال", "maha": "مها", "mona": "منى", "muna": "منى",
    "najwa": "نجوى", "nawal": "نوال", "rania": "رانيا", "randa": "رندة", "rola": "رولا", "roula": "رولا", "salma": "سلمى", "samar": "سمر",
    "samira": "سميرة", "souad": "سعاد", "suad": "سعاد", "wafa": "وفاء", "yasmine": "ياسمين", "yasmin": "ياسمين", "zahra": "زهراء",
    "aya": "آية", "amal": "أمل", "abir": "عبير", "dalal": "دلال", "ghada": "غادة", "hanadi": "هنادي", "jinane": "جنان", "lara": "لارا",
    "loubna": "لبنى", "mirna": "ميرنا", "nisrine": "نسرين", "rasha": "رشا", "racha": "رشا", "sawsan": "سوسن", "siham": "سهام",
    "tamara": "تمارا", "wardeh": "وردة", "zeina": "زينة", "zina": "زينة", "aline": "ألين", "chantal": "شانتال", "georgette": "جورجيت",
    # family names
    "saber": "صابر", "saab": "صعب", "haddad": "حداد", "khoury": "خوري", "khouri": "خوري", "el khoury": "الخوري", "nassar": "نصار",
    "hajj": "حاج", "el hajj": "الحاج", "hage": "الحاج", "chamoun": "شمعون", "gemayel": "الجميل", "frangieh": "فرنجية", "karam": "كرم",
    "aoun": "عون", "salameh": "سلامة", "salame": "سلامة", "harb": "حرب", "daher": "ضاهر", "dagher": "داغر", "fakhoury": "فاخوري",
    "hamdan": "حمدان", "hammoud": "حمود", "jaber": "جابر", "kassab": "قصاب", "mansour": "منصور", "mourad": "مراد", "mrad": "مراد",
    "nasr": "نصر", "rizk": "رزق", "saad.": "سعد", "sleiman": "سليمان", "suleiman": "سليمان", "tabbara": "طبارة", "yammine": "يمين",
    "zein.": "الزين", "zeidan": "زيدان", "abou": "أبو", "abu": "أبو", "bou": "بو", "ben": "بن", "bin": "بن", "el": "ال", "al": "ال",
    "chahine": "شاهين", "shahine": "شاهين", "fayad": "فياض", "hijazi": "حجازي", "hammad": "حماد", "itani": "عيتاني", "jouni": "جوني",
    "khalife": "خليفة", "khalifeh": "خليفة", "makki": "مكي", "moussawi": "موسوي", "rifai": "رفاعي", "sabbagh": "صباغ", "sayegh": "صايغ",
    "chehab": "شهاب", "shehab": "شهاب", "atallah": "عطالله", "awad": "عواد", "azar": "عازار", "boustany": "البستاني", "chidiac": "شدياق",
    "fakhry": "فخري", "habchi": "حبشي", "issa.": "عيسى", "maalouf": "معلوف", "matar": "مطر", "nahas": "نحاس", "sfeir": "صفير",
    "jaoude": "جودة", "daou": "ضو", "roukoz": "روكز", "wehbe": "وهبة", "tohme.": "طعمة", "kanj": "كنج", "sabrine": "صابرين",
    "tannous": "طنوس", "tohme": "طعمة", "zoghbi": "زغبي", "zgheib": "زغيب", "ghanem": "غانم", "geagea": "جعجع", "kanaan": "كنعان",
}

PLACES = {
    "beirut": "بيروت", "tripoli": "طرابلس", "saida": "صيدا", "sidon": "صيدا", "sour": "صور", "tyre": "صور", "zahle": "زحلة",
    "zahleh": "زحلة", "jounieh": "جونية", "byblos": "جبيل", "jbeil": "جبيل", "baabda": "بعبدا", "aley": "عاليه", "chouf": "الشوف",
    "metn": "المتن", "keserwan": "كسروان", "kesrouan": "كسروان", "batroun": "البترون", "koura": "الكورة", "zgharta": "زغرتا",
    "akkar": "عكار", "baalbek": "بعلبك", "hermel": "الهرمل", "nabatieh": "النبطية", "marjayoun": "مرجعيون", "bint jbeil": "بنت جبيل",
    "hasbaya": "حاصبيا", "jezzine": "جزين", "rashaya": "راشيا", "west bekaa": "البقاع الغربي", "bekaa": "البقاع", "hazmieh": "الحازمية",
    "hazmiyeh": "الحازمية", "zouk mikael": "ذوق مكايل", "zouk mosbeh": "ذوق مصبح", "jdeideh": "الجديدة", "dekwaneh": "الدكوانة",
    "sin el fil": "سن الفيل", "achrafieh": "الأشرفية", "ashrafieh": "الأشرفية", "hamra": "الحمرا", "verdun": "فردان", "dbayeh": "ضبية",
    "antelias": "أنطلياس", "jal el dib": "جل الديب", "broummana": "برمانا", "beit mery": "بيت مري", "kaslik": "الكسليك",
    "chiyah": "الشياح", "ghobeiry": "الغبيري", "haret hreik": "حارة حريك", "bourj hammoud": "برج حمود", "mina": "الميناء",
    "el mina": "الميناء", "halba": "حلبا", "chekka": "شكا", "amchit": "عمشيت", "damour": "الدامور", "khaldeh": "خلدة",
    "choueifat": "الشويفات", "mount lebanon": "جبل لبنان", "north": "الشمال", "south": "الجنوب", "lebanon": "لبنان", "syria": "سوريا",
    "main street": "الشارع الرئيسي", "main road": "الطريق العام", "street": "شارع", "st": "شارع", "st.": "شارع", "road": "طريق", "building": "بناية", "bldg": "بناية", "floor": "طابق", "near": "قرب",
}

NATIONALITIES = {
    "lebanese": "لبنانية", "syrian": "سورية", "palestinian": "فلسطينية", "egyptian": "مصرية", "iraqi": "عراقية", "jordanian": "أردنية",
    "sudanese": "سودانية", "ethiopian": "إثيوبية", "filipino": "فلبينية", "bangladeshi": "بنغلادشية", "sri lankan": "سريلانكية",
    "indian": "هندية", "nepalese": "نيبالية", "kenyan": "كينية", "ghanaian": "غانية", "nigerian": "نيجيرية", "french": "فرنسية",
    "american": "أميركية", "british": "بريطانية", "canadian": "كندية", "turkish": "تركية", "armenian": "أرمنية", "saudi": "سعودية",
    "emirati": "إماراتية", "kuwaiti": "كويتية", "qatari": "قطرية",
}

JOB_PHRASES = {
    "sales manager": "مدير مبيعات", "general manager": "مدير عام", "financial manager": "مدير مالي", "finance manager": "مدير مالي",
    "chief accountant": "رئيس المحاسبة", "head accountant": "رئيس المحاسبة", "office manager": "مدير مكتب", "hr manager": "مدير الموارد البشرية",
    "human resources": "الموارد البشرية", "sales representative": "مندوب مبيعات", "sales rep": "مندوب مبيعات", "customer service": "خدمة الزبائن",
    "it manager": "مدير معلوماتية", "operations manager": "مدير العمليات", "marketing manager": "مدير تسويق", "project manager": "مدير مشروع",
    "store keeper": "أمين مستودع", "storekeeper": "أمين مستودع", "office boy": "حاجب", "cleaning lady": "عاملة تنظيف",
}
JOB_WORDS = {
    "manager": "مدير", "director": "مدير", "assistant": "مساعد", "accountant": "محاسب", "secretary": "سكرتيرة", "driver": "سائق",
    "cashier": "أمين صندوق", "engineer": "مهندس", "technician": "تقني", "worker": "عامل", "labourer": "عامل", "laborer": "عامل",
    "salesman": "بائع", "seller": "بائع", "sales": "مبيعات", "marketing": "تسويق", "purchasing": "مشتريات", "procurement": "مشتريات",
    "supervisor": "مشرف", "officer": "موظف", "employee": "موظف", "clerk": "موظف", "receptionist": "موظفة استقبال", "guard": "حارس",
    "cleaner": "عامل تنظيف", "cook": "طباخ", "chef": "طباخ", "waiter": "نادل", "nurse": "ممرضة", "teacher": "أستاذ", "pharmacist": "صيدلي",
    "doctor": "طبيب", "lawyer": "محامي", "auditor": "مدقق حسابات", "consultant": "مستشار", "designer": "مصمم", "developer": "مبرمج",
    "programmer": "مبرمج", "it": "معلوماتية", "warehouse": "مستودع", "logistics": "لوجستيك", "finance": "مالية", "financial": "مالي",
    "administrative": "إداري", "admin": "إداري", "operations": "عمليات", "production": "إنتاج", "quality": "جودة", "maintenance": "صيانة",
    "electrician": "كهربائي", "plumber": "سنكري", "mechanic": "ميكانيكي", "carpenter": "نجار", "painter": "دهان", "general": "عام",
    "senior": "أول", "junior": "مبتدئ", "head": "رئيس", "chief": "رئيس", "representative": "مندوب", "coordinator": "منسق", "agent": "وكيل",
    "and": "و", "of": "", "&": "و",
}
HEADS = {"manager", "director", "assistant", "supervisor", "officer", "engineer", "representative", "coordinator", "head", "chief", "agent"}

# letter-by-letter, for a word that is in no list (longest groups first)
GROUPS = (("sch", "ش"), ("sh", "ش"), ("ch", "ش"), ("kh", "خ"), ("gh", "غ"), ("th", "ث"), ("dh", "ذ"), ("ph", "ف"), ("ou", "و"),
          ("oo", "و"), ("ee", "ي"), ("ei", "ي"), ("ai", "ي"), ("ay", "اي"), ("aa", "ا"), ("ie", "ي"), ("ck", "ك"), ("qu", "ك"))
LETTERS = {"b": "ب", "t": "ت", "j": "ج", "h": "ه", "d": "د", "r": "ر", "z": "ز", "s": "س", "f": "ف", "q": "ق", "k": "ك", "l": "ل",
           "m": "م", "n": "ن", "w": "و", "y": "ي", "g": "ج", "v": "ف", "p": "ب", "c": "ك", "x": "كس", "a": "ا", "i": "ي", "o": "و", "u": "و",
           "e": "", "é": "ي", "è": "ي", "'": "ع"}


def transliterate(word: str) -> str:
    """One Latin word in Arabic letters (a proposal for an unknown name)."""
    w = word.lower().strip()
    if not w: return ""
    if re.search(r"[؀-ۿ]", w) or not re.search(r"[a-zé]", w): return word  # already Arabic, or a number
    end = ""
    if len(w) > 3 and w.endswith(("ieh", "iyeh", "iya", "iyya")): w, end = re.sub(r"(iyeh|ieh|iyya|iya)$", "", w), "ية"
    elif len(w) > 3 and w.endswith(("eh", "ah", "a")) and not w.endswith(("aa",)) and w not in ("allah",): w, end = re.sub(r"(eh|ah|a)$", "", w), "ة"
    elif len(w) > 3 and re.search(r"[bdfhklmrt]e$", w): w, end = w[:-1], "ة"  # Lebanese family names: Salame, Wehbe, Khalife
    out = []
    if w[:1] in "ae": out.append("أ" if w[:1] == "a" else "إ"); w = w[1:]
    elif w[:1] == "i": out.append("إ"); w = w[1:]
    elif w[:2] in ("ou", "oo") or w[:1] in "ou": out.append("أو"); w = w[2:] if w[:2] in ("ou", "oo") else w[1:]
    i, previous = 0, ""
    while i < len(w):
        for group, letter in GROUPS:
            if w.startswith(group, i):
                piece, i = letter, i + len(group); break
        else:
            piece, i = LETTERS.get(w[i], ""), i + 1
        if piece and piece == previous and piece not in "اوي": continue  # double consonant written once (bassam -> بسام)
        out.append(piece); previous = piece or previous
    return "".join(out) + end


# 2.9.112: address words (place kind); in Arabic the word comes first: "Hamra Street" -> "شارع الحمرا"
ADDRESS_WORDS = {"street": "شارع", "st": "شارع", "st.": "شارع", "road": "طريق", "rd": "طريق", "rd.": "طريق", "avenue": "جادة",
                 "ave": "جادة", "highway": "أوتوستراد", "square": "ساحة", "building": "بناية", "bldg": "بناية", "bldg.": "بناية",
                 "floor": "طابق", "center": "سنتر", "centre": "سنتر", "tower": "برج", "near": "قرب",
                 "next": "بجانب", "to": "", "block": "بلوك", "main road": "الطريق العام", "main street": "الشارع العام", "old road": "الطريق القديمة"}


# 2.9.112: company names - business words translated, the legal form at the end ("Sample Trading SARL" -> "سامبل للتجارة ش.م.م.")
LEGAL_FORMS = {"sarl": "ش.م.م.", "s.a.r.l": "ش.م.م.", "s.a.r.l.": "ش.م.م.", "sal": "ش.م.ل.", "s.a.l": "ش.م.ل.", "s.a.l.": "ش.م.ل.",
               "llc": "ش.م.م.", "ltd": "المحدودة", "inc": "ش.م.", "co": "وشركاه", "holding": "هولدنغ", "offshore": "أوف شور"}
BUSINESS_WORDS = {"trading": "للتجارة", "trade": "للتجارة", "company": "شركة", "group": "مجموعة", "audit": "للتدقيق", "auditing": "للتدقيق",
                  "accounting": "للمحاسبة", "consulting": "للاستشارات", "consultancy": "للاستشارات", "services": "للخدمات", "service": "للخدمات",
                  "contracting": "للمقاولات", "construction": "للبناء", "engineering": "للهندسة", "industries": "للصناعات", "industry": "للصناعة",
                  "industrial": "الصناعية", "commercial": "التجارية", "general": "العامة", "international": "الدولية", "lebanon": "لبنان",
                  "lebanese": "اللبنانية", "real estate": "العقارية", "estate": "العقارية", "pharmacy": "صيدلية", "pharma": "للأدوية",
                  "restaurant": "مطعم", "hotel": "فندق", "bakery": "فرن", "transport": "للنقل", "import": "للاستيراد", "export": "للتصدير",
                  "electric": "للكهرباء", "electronics": "للإلكترونيات", "technology": "للتكنولوجيا", "tech": "للتكنولوجيا", "solutions": "للحلول",
                  "management": "للإدارة", "foods": "للأغذية", "food": "للأغذية", "medical": "الطبية", "insurance": "للتأمين", "printing": "للطباعة",
                  "sons": "أولاده", "brothers": "إخوان", "and": "و", "&": "و", "for": "", "the": "", "of": ""}


def company_arabic(text) -> str:
    """A company name in Arabic: known business words translated, names written in Arabic letters, the legal form last."""
    text = str(text or "").strip()
    if not text or (re.search(r"[؀-ۿ]", text) and not re.search(r"[A-Za-z]", text)): return text
    words = [w for w in re.split(r"[\s,]+", text) if w]
    legal = [LEGAL_FORMS[w.lower().rstrip(".") if w.lower().rstrip(".") in LEGAL_FORMS else w.lower()] for w in words
             if w.lower() in LEGAL_FORMS or w.lower().rstrip(".") in LEGAL_FORMS]
    out = []
    for w in words:
        low = w.lower()
        if low in LEGAL_FORMS or low.rstrip(".") in LEGAL_FORMS: continue
        if low in BUSINESS_WORDS:
            if BUSINESS_WORDS[low]: out.append(BUSINESS_WORDS[low])
        else:
            found = NAMES.get(low) or PLACES.get(low)
            out.append(found or transliterate(w[:-1] if len(w) > 4 and low.endswith(("ple", "ble", "ge")) else w))
    return " ".join(out + legal).strip()


def _lookup(phrase: str, *tables) -> str | None:
    for table in tables:
        if phrase in table: return table[phrase]
    return None


def to_arabic(text, kind: str = "name") -> str:
    """kind: "name" (person), "place" (place of birth, address), "nationality", "job"."""
    text = str(text or "").strip()
    if not text: return ""
    if re.search(r"[؀-ۿ]", text) and not re.search(r"[A-Za-z]", text): return text  # already Arabic
    low = re.sub(r"\s+", " ", text.lower())
    if kind == "company": return company_arabic(text)
    if kind == "nationality":
        return NATIONALITIES.get(low) or NATIONALITIES.get(low.rstrip("e")) or to_arabic(text, "name")
    if kind == "job":
        if low in JOB_PHRASES: return JOB_PHRASES[low]
        words = [w for w in re.split(r"[\s/,-]+", low) if w]
        if len(words) > 1 and words[-1] in HEADS:  # "sales manager" -> "مدير مبيعات": the head word comes first in Arabic
            words = [words[-1]] + words[:-1]
        return " ".join(filter(None, (JOB_WORDS.get(w) if w in JOB_WORDS else transliterate(w) for w in words)))
    tables = (PLACES, NAMES) if kind == "place" else (NAMES, PLACES)
    if kind == "place":
        tables = tables + (ADDRESS_WORDS,)
        moved = re.match(r"^(.+?)\s+(street|st\.?|road|rd\.?|avenue|ave\.?|building|bldg\.?|tower|center|centre|square)$", text, re.I)
        if moved and "," not in text and low not in ADDRESS_WORDS: return to_arabic(moved.group(2), "place") + " " + to_arabic(moved.group(1), "place")
    whole = _lookup(low, *tables)
    if whole: return whole
    parts = re.split(r"(\s+|-|,|/)", text)
    out, i = [], 0
    while i < len(parts):
        part = parts[i]
        if not part.strip() or part in ("-", ",", "/"):
            out.append(" - " if part == "-" else "، " if part == "," else part); i += 1; continue
        # two-word names first (el khoury, zouk mikael, bint jbeil ...)
        if i + 2 < len(parts):
            pair = f"{part.lower()} {parts[i + 2].lower()}"
            found = _lookup(pair, *tables)
            if found: out.append(found); i += 3; continue
        word = part.lower()
        found = _lookup(word, *tables) if kind != "name" or word not in ("el", "al") else None
        if word in ("el", "al") and i + 2 < len(parts):  # el / al + name -> ال joined to the next word
            nxt = parts[i + 2]; out.append("ال" + (_lookup(nxt.lower(), *tables) or transliterate(nxt)).lstrip("ال")); i += 3; continue
        out.append(found or transliterate(part)); i += 1
    return re.sub(r"\s+", " ", "".join(out)).strip()
