"""2.9.109: the financial statements, notes and auditor's report in French and Arabic (English stays the default).

Every fixed text of financial_statements.build is looked up here by its English wording; the default note and audit
texts have their own translation with the same {placeholders}. A text the user rewrote himself is printed as he wrote it."""
from __future__ import annotations

LANGUAGES = {"en": "English", "fr": "Français", "ar": "العربية"}

MONTHS = {
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
    "fr": ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"],
    "ar": ["كانون الثاني", "شباط", "آذار", "نيسان", "أيار", "حزيران", "تموز", "آب", "أيلول", "تشرين الأول", "تشرين الثاني", "كانون الأول"],
}

LINE_TITLES = {
    "fr": {"ppe": "Immobilisations corporelles", "intangible": "Immobilisations incorporelles", "noncurrent_assets": "Autres actifs non courants",
           "inventory": "Stocks", "receivables": "Clients et autres débiteurs", "cash": "Trésorerie et équivalents de trésorerie",
           "current_assets": "Autres actifs courants", "capital": "Capital social", "reserves": "Réserves", "retained": "Résultats reportés",
           "noncurrent_liabilities": "Passifs non courants et provisions", "payables": "Fournisseurs et autres créditeurs",
           "current_liabilities": "Autres passifs courants", "revenue": "Chiffre d'affaires", "other_income": "Autres produits",
           "materials": "Coût des marchandises et matières", "services": "Services extérieurs", "staff": "Charges de personnel",
           "taxes": "Impôts et taxes", "finance": "Charges financières nettes", "depreciation": "Dotations aux amortissements et provisions",
           "other_expenses": "Autres charges", "income_tax": "Impôt sur le résultat", "unmapped": "Comptes à classer"},
    "ar": {"ppe": "الممتلكات والمنشآت والمعدات", "intangible": "الموجودات غير الملموسة", "noncurrent_assets": "موجودات غير متداولة أخرى",
           "inventory": "المخزون", "receivables": "الذمم المدينة التجارية والأخرى", "cash": "النقد وما يعادله",
           "current_assets": "موجودات متداولة أخرى", "capital": "رأس المال", "reserves": "الاحتياطيات", "retained": "الأرباح المدوّرة",
           "noncurrent_liabilities": "مطلوبات غير متداولة ومؤونات", "payables": "الذمم الدائنة التجارية والأخرى",
           "current_liabilities": "مطلوبات متداولة أخرى", "revenue": "الإيرادات", "other_income": "إيرادات أخرى",
           "materials": "كلفة البضائع والمواد", "services": "خدمات خارجية", "staff": "أعباء المستخدمين", "taxes": "ضرائب ورسوم",
           "finance": "أعباء مالية صافية", "depreciation": "الاستهلاكات والمؤونات", "other_expenses": "أعباء أخرى",
           "income_tax": "ضريبة الدخل", "unmapped": "حسابات بحاجة للتصنيف"},
}

# English wording -> French, Arabic ({x} placeholders are kept)
TEXTS = {
    "INDEPENDENT AUDITOR'S REPORT": ("RAPPORT DE L'AUDITEUR INDÉPENDANT", "تقرير مدقق الحسابات المستقل"),
    "Opinion": ("Opinion", "الرأي"),
    "Basis for Opinion": ("Fondement de l'opinion", "أساس الرأي"),
    "Key Audit Matters": ("Points clés de l'audit", "أمور التدقيق الرئيسية"),
    "Other Information": ("Autres informations", "معلومات أخرى"),
    "Responsibilities of Management and Those Charged with Governance for the Financial Statements":
        ("Responsabilités de la direction et des responsables de la gouvernance à l'égard des états financiers",
         "مسؤوليات الإدارة والمكلفين بالحوكمة عن البيانات المالية"),
    "Auditor's Responsibilities for the Audit of the Financial Statements":
        ("Responsabilités de l'auditeur à l'égard de l'audit des états financiers", "مسؤوليات مدقق الحسابات عن تدقيق البيانات المالية"),
    "Report on Other Legal and Regulatory Requirements": ("Rapport relatif aux autres obligations légales et réglementaires",
                                                          "تقرير حول المتطلبات القانونية والتنظيمية الأخرى"),
    "ASSETS": ("ACTIF", "الموجودات"), "Non-current assets": ("Actifs non courants", "الموجودات غير المتداولة"),
    "Total non-current assets": ("Total des actifs non courants", "مجموع الموجودات غير المتداولة"),
    "Current assets": ("Actifs courants", "الموجودات المتداولة"), "Total current assets": ("Total des actifs courants", "مجموع الموجودات المتداولة"),
    "TOTAL ASSETS": ("TOTAL DE L'ACTIF", "مجموع الموجودات"), "EQUITY AND LIABILITIES": ("CAPITAUX PROPRES ET PASSIF", "حقوق الملكية والمطلوبات"),
    "Equity": ("Capitaux propres", "حقوق الملكية"), "Profit for the year": ("Résultat de l'exercice", "ربح السنة"),
    "Profit for the year to date": ("Résultat de la période", "ربح الفترة"), "Total equity": ("Total des capitaux propres", "مجموع حقوق الملكية"),
    "Liabilities": ("Passifs", "المطلوبات"), "Total liabilities": ("Total des passifs", "مجموع المطلوبات"),
    "TOTAL EQUITY AND LIABILITIES": ("TOTAL DES CAPITAUX PROPRES ET DU PASSIF", "مجموع حقوق الملكية والمطلوبات"),
    " (see review points)": (" (voir points de revue)", " (راجع نقاط المراجعة)"), "Notes": ("Notes", "إيضاح"),
    "Total income": ("Total des produits", "مجموع الإيرادات"), "Profit / (loss) before tax": ("Résultat avant impôt", "الربح / (الخسارة) قبل الضريبة"),
    "PROFIT / (LOSS) FOR THE YEAR": ("RÉSULTAT NET DE L'EXERCICE", "صافي ربح / (خسارة) السنة"),
    "PROFIT / (LOSS) FOR THE PERIOD": ("RÉSULTAT NET DE LA PÉRIODE", "صافي ربح / (خسارة) الفترة"),
    "Other comprehensive income": ("Autres éléments du résultat global", "الدخل الشامل الآخر"),
    "TOTAL COMPREHENSIVE INCOME": ("RÉSULTAT GLOBAL TOTAL", "مجموع الدخل الشامل"),
    "Balance at start ({date})": ("Solde au début ({date})", "الرصيد في البداية ({date})"),
    "Profit / (loss) for the period": ("Résultat de la période", "ربح / (خسارة) الفترة"),
    "Capital movements, dividends and transfers": ("Mouvements du capital, dividendes et virements", "حركة رأس المال والأنصبة والتحويلات"),
    "Balance at end ({date})": ("Solde à la fin ({date})", "الرصيد في النهاية ({date})"),
    "Share capital": ("Capital social", "رأس المال"), "Reserves": ("Réserves", "الاحتياطيات"),
    "Retained earnings": ("Résultats reportés", "الأرباح المدوّرة"), "Total": ("Total", "المجموع"),
    "CASH FLOWS FROM OPERATING ACTIVITIES": ("FLUX DE TRÉSORERIE LIÉS AUX ACTIVITÉS OPÉRATIONNELLES", "التدفقات النقدية من الأنشطة التشغيلية"),
    "Adjustment: depreciation and amortisation": ("Ajustement : amortissements", "تعديل: الاستهلاكات والإطفاءات"),
    "Adjustment: movement in provisions (end of service and others)": ("Ajustement : variation des provisions (fin de service et autres)",
                                                                       "تعديل: حركة المؤونات (تعويض نهاية الخدمة وغيرها)"),
    "(Increase) / decrease in inventories": ("(Augmentation) / diminution des stocks", "(الزيادة) / النقص في المخزون"),
    "(Increase) / decrease in trade and other receivables": ("(Augmentation) / diminution des clients et autres débiteurs",
                                                             "(الزيادة) / النقص في الذمم المدينة"),
    "(Increase) / decrease in other current assets": ("(Augmentation) / diminution des autres actifs courants", "(الزيادة) / النقص في الموجودات المتداولة الأخرى"),
    "Increase / (decrease) in trade and other payables": ("Augmentation / (diminution) des fournisseurs et autres créditeurs",
                                                          "الزيادة / (النقص) في الذمم الدائنة"),
    "Increase / (decrease) in other current liabilities": ("Augmentation / (diminution) des autres passifs courants",
                                                           "الزيادة / (النقص) في المطلوبات المتداولة الأخرى"),
    "Movement in accounts to classify": ("Variation des comptes à classer", "حركة الحسابات بحاجة للتصنيف"),
    "Net cash from operating activities": ("Trésorerie nette liée aux activités opérationnelles", "صافي النقد من الأنشطة التشغيلية"),
    "CASH FLOWS FROM INVESTING ACTIVITIES": ("FLUX DE TRÉSORERIE LIÉS AUX ACTIVITÉS D'INVESTISSEMENT", "التدفقات النقدية من الأنشطة الاستثمارية"),
    "Acquisition / (disposal) of non-current assets, net": ("Acquisitions / (cessions) d'actifs non courants, net", "شراء / (بيع) موجودات غير متداولة، صافي"),
    "Net cash used in investing activities": ("Trésorerie nette liée aux activités d'investissement", "صافي النقد المستخدم في الأنشطة الاستثمارية"),
    "CASH FLOWS FROM FINANCING ACTIVITIES": ("FLUX DE TRÉSORERIE LIÉS AUX ACTIVITÉS DE FINANCEMENT", "التدفقات النقدية من الأنشطة التمويلية"),
    "Capital, borrowings and dividends, net": ("Capital, emprunts et dividendes, net", "رأس المال والقروض والأنصبة، صافي"),
    "Net cash from financing activities": ("Trésorerie nette liée aux activités de financement", "صافي النقد من الأنشطة التمويلية"),
    "NET INCREASE / (DECREASE) IN CASH": ("VARIATION NETTE DE LA TRÉSORERIE", "صافي الزيادة / (النقص) في النقد"),
    "Cash and cash equivalents at start": ("Trésorerie à l'ouverture", "النقد وما يعادله في بداية الفترة"),
    "CASH AND CASH EQUIVALENTS AT END": ("TRÉSORERIE À LA CLÔTURE", "النقد وما يعادله في نهاية الفترة"),
    # 2.9.132
    "Total expenses": ("Total des charges", "مجموع المصاريف"),
    "Cash and cash equivalents in the statement of financial position": ("Trésorerie à l'état de la situation financière", "النقد وما يعادله في بيان المركز المالي"),
    "Bank overdrafts (in other current liabilities)": ("Découverts bancaires (dans les autres passifs courants)", "حسابات مصرفية مكشوفة (ضمن المطلوبات المتداولة الأخرى)"),
    "STATEMENT OF FINANCIAL POSITION as at {end_text}": ("ÉTAT DE LA SITUATION FINANCIÈRE au {end_text}", "بيان المركز المالي كما في {end_text}"),
    "STATEMENT OF PROFIT OR LOSS AND OTHER COMPREHENSIVE INCOME {for_period}": (
        "ÉTAT DU RÉSULTAT NET ET DES AUTRES ÉLÉMENTS DU RÉSULTAT GLOBAL {for_period}", "بيان الربح أو الخسارة والدخل الشامل الآخر {for_period}"),
    "STATEMENT OF CHANGES IN EQUITY ({basis})": ("ÉTAT DES VARIATIONS DES CAPITAUX PROPRES ({basis})", "بيان التغيرات في حقوق الملكية ({basis})"),
    "STATEMENT OF CASH FLOWS {for_period}": ("TABLEAU DES FLUX DE TRÉSORERIE {for_period}", "بيان التدفقات النقدية {for_period}"),
    "for the year ended {end_text}": ("pour l'exercice clos le {end_text}", "للسنة المنتهية في {end_text}"),
    "for the period from {start} to {end_text}": ("pour la période du {start} au {end_text}", "للفترة من {start} إلى {end_text}"),
    "year": ("exercice", "السنة"), "period from {start}": ("période du {start}", "الفترة من {start}"),
    "NOTES TO THE FINANCIAL STATEMENTS - ": ("NOTES ANNEXES AUX ÉTATS FINANCIERS - ", "إيضاحات حول البيانات المالية - "),
    "1. GENERAL INFORMATION": ("1. INFORMATIONS GÉNÉRALES", "1. معلومات عامة"),
    "2. BASIS OF PREPARATION": ("2. BASE DE PRÉPARATION", "2. أسس الإعداد"),
    "3. MATERIAL ACCOUNTING POLICIES": ("3. MÉTHODES COMPTABLES SIGNIFICATIVES", "3. السياسات المحاسبية الهامة"),
    "4. JUDGEMENTS AND ESTIMATES": ("4. JUGEMENTS ET ESTIMATIONS", "4. الأحكام والتقديرات"),
    "Text": ("Texte", "النص"), "Description": ("Libellé", "البيان"), "TOTAL": ("TOTAL", "المجموع"),
    "Income tax": ("Impôt sur le résultat", "ضريبة الدخل"), "Currency and inflation": ("Monnaie et inflation", "العملة والتضخم"),
    "Financial risk management": ("Gestion des risques financiers", "إدارة المخاطر المالية"),
    "Related parties and commitments": ("Parties liées et engagements", "الأطراف ذات العلاقة والالتزامات"),
    "Events and going concern": ("Événements postérieurs et continuité d'exploitation", "الأحداث اللاحقة واستمرارية النشاط"),
    "Additional disclosures": ("Informations complémentaires", "إفصاحات إضافية"),
    "Approval of the financial statements": ("Approbation des états financiers", "الموافقة على البيانات المالية"),
    "Financial Statements, Notes and Audit Report": ("États financiers, notes annexes et rapport d'audit", "البيانات المالية والإيضاحات وتقرير التدقيق"),
    "Financial Statements and Notes": ("États financiers et notes annexes", "البيانات المالية والإيضاحات"),  # 2.9.121
    "Year ended ": ("Exercice clos le ", "السنة المنتهية في "), "Period ended ": ("Période close le ", "الفترة المنتهية في "),
    " - with comparative figures": (" - avec chiffres comparatifs", " - مع أرقام المقارنة"),
    "Presentation currency: {basis}": ("Monnaie de présentation : {basis}", "عملة العرض: {basis}"), "Auditor: {firm}": ("Auditeur : {firm}", "مدقق الحسابات: {firm}"),
    "first-in first-out (FIFO)": ("premier entré, premier sorti (FIFO)", "الوارد أولاً صادر أولاً (FIFO)"),
    "weighted average cost": ("coût moyen pondéré", "المتوسط المرجّح للكلفة"),
}

NARRATIVES = {
    "fr": {
        "Entity and activities": (
            "{company} (la « Société ») est une {legal_form} immatriculée au Liban{address_text} au registre du commerce sous le numéro {cr_number}, "
            "constituée le {incorporation_date}. Son numéro fiscal (MoF) est {tax_number}.\nLes activités principales de la Société sont : "
            "{activities}.\nActionnaires / associés : {shareholders}.\nAdministrateurs / gérants : {directors}."
        ),
        "Basis of preparation": (
            "Les états financiers ont été préparés conformément aux Normes internationales d'information financière (IFRS) selon la convention du coût "
            "historique et sont présentés en {basis}. Les montants enregistrés dans d'autres monnaies sont convertis aux taux de change enregistrés dans "
            "les livres.\nLes états financiers ont été approuvés par la direction le {approval_date}. [Confirmer l'hypothèse de continuité "
            "d'exploitation.]"
        ),
        "Material accounting policies": (
            "Les produits sont comptabilisés lorsque le contrôle des biens ou des services est transféré au client, nets des remises et de la taxe sur "
            "la valeur ajoutée.\nLes stocks sont évalués au plus faible du coût et de la valeur nette de réalisation ; le coût est déterminé selon la "
            "méthode du {inventory_method}.\nLes immobilisations corporelles sont comptabilisées au coût diminué des amortissements cumulés ; "
            "l'amortissement est calculé selon le mode linéaire sur la durée d'utilité des actifs.\nLes créances clients sont comptabilisées au montant "
            "facturé diminué d'une dépréciation pour pertes de crédit attendues.\nLa trésorerie et les équivalents de trésorerie comprennent les fonds "
            "en caisse et les soldes bancaires.\nLes dettes fournisseurs sont comptabilisées au montant dû pour les biens et services reçus.\nLes "
            "opérations en devises sont enregistrées aux taux de change des dates des opérations ; les soldes monétaires sont convertis aux taux "
            "enregistrés à la date de clôture.\nLa taxe sur la valeur ajoutée est comptabilisée conformément à la loi libanaise sur la TVA ; la TVA "
            "récupérable est présentée avec les créances et la TVA à payer avec les dettes.\nL'impôt sur le résultat est provisionné conformément à la "
            "législation fiscale libanaise.\nLes provisions sont comptabilisées lorsque la Société a une obligation actuelle pouvant être évaluée de "
            "façon fiable ; les indemnités de fin de service suivent le Code du travail libanais et les règlements de la CNSS."
        ),
        "Judgements and estimates": (
            "La préparation des états financiers exige de la direction des jugements et des estimations, principalement pour les pertes de crédit "
            "attendues sur les créances, la valeur nette de réalisation des stocks, la durée d'utilité des immobilisations et les provisions. [Compléter "
            "avec les jugements propres à l'entité.]"
        ),
        "Share capital": (
            "Le capital social de la Société s'élève à {share_capital}, entièrement libéré. [Confirmer le nombre et la valeur nominale des actions et "
            "toute variation au cours de l'exercice.]"
        ),
        "Income tax": (
            "L'impôt sur le résultat est calculé conformément à la loi libanaise relative à l'impôt sur le revenu sur le bénéfice imposable de la "
            "période, après réintégration des charges non déductibles. [Insérer le rapprochement entre le résultat comptable et le résultat fiscal et le "
            "taux d'impôt appliqué.]"
        ),
        "Currency and inflation": (
            "La monnaie fonctionnelle et de présentation est le {basis}. Les soldes en autres monnaies sont convertis aux taux enregistrés dans les "
            "livres. [Évaluer l'effet de la situation économique au Liban, des taux de change multiples et d'IAS 29 le cas échéant.]"
        ),
        "Financial risk management": (
            "La Société est exposée au risque de crédit, principalement sur les créances clients et les soldes bancaires ; au risque de liquidité ; et "
            "au risque de change sur les soldes et opérations en monnaies autres que le {basis}, y compris l'effet des taux de change multiples au "
            "Liban. La direction suit ces risques régulièrement. [Compléter avec les politiques de la Société et les principaux montants exposés.]"
        ),
        "Related parties and commitments": (
            "[Lister les parties liées (actionnaires, administrateurs, sociétés sous contrôle commun), les transactions et soldes avec elles, les "
            "engagements et passifs éventuels.]"
        ),
        "Events and going concern": "[Décrire les événements postérieurs à la date de clôture (IAS 10) et l'évaluation de la continuité d'exploitation.]",
        "Additional disclosures": "[Ajouter les autres informations utiles : contrats de location, gestion du capital, chiffres comparatifs reclassés.]",
        "Approval of the financial statements": "Les états financiers ont été approuvés par la direction le {approval_date}.",
    },
    "ar": {
        "Entity and activities": (
            "{company} (\"الشركة\") هي {legal_form} مسجلة في لبنان{address_text} في السجل التجاري تحت الرقم {cr_number}، تأسست بتاريخ "
            "{incorporation_date}. رقمها المالي لدى وزارة المالية {tax_number}.\nتتمثل النشاطات الرئيسية للشركة في: {activities}.\nالمساهمون / الشركاء: "
            "{shareholders}.\nأعضاء مجلس الإدارة / المدراء: {directors}."
        ),
        "Basis of preparation": (
            "أُعدّت البيانات المالية وفقاً للمعايير الدولية لإعداد التقارير المالية (IFRS) على أساس مبدأ الكلفة التاريخية، وهي معروضة بـ{basis}. تُحوَّل "
            "المبالغ المسجّلة بعملات أخرى بأسعار الصرف المسجّلة في الدفاتر.\nوافقت الإدارة على إصدار البيانات المالية بتاريخ {approval_date}. [تأكيد "
            "أساس استمرارية النشاط.]"
        ),
        "Material accounting policies": (
            "تُقيَّد الإيرادات عند انتقال السيطرة على البضائع أو الخدمات إلى الزبون، بعد تنزيل الحسومات والضريبة على القيمة المضافة.\nيُقيَّم المخزون "
            "بالكلفة أو صافي القيمة القابلة للتحقق أيهما أقل، وتُحدَّد الكلفة وفق طريقة {inventory_method}.\nتظهر الممتلكات والمنشآت والمعدات بالكلفة "
            "بعد تنزيل الاستهلاكات المتراكمة، ويُحتسب الاستهلاك بالطريقة الثابتة على مدى العمر الإنتاجي للموجودات.\nتظهر الذمم المدينة التجارية بقيمة "
            "الفواتير بعد تنزيل مؤونة الخسائر الائتمانية المتوقعة.\nيتضمن النقد وما يعادله النقد في الصندوق والأرصدة لدى المصارف.\nتظهر الذمم الدائنة "
            "التجارية بالمبالغ المستحقة عن البضائع والخدمات المستلمة.\nتُسجَّل العمليات بالعملات الأجنبية بأسعار الصرف بتاريخ العمليات، وتُحوَّل الأرصدة "
            "النقدية بالأسعار المسجلة بتاريخ البيانات المالية.\nتُحتسب الضريبة على القيمة المضافة وفقاً لقانون الضريبة على القيمة المضافة اللبناني، "
            "وتظهر الضريبة القابلة للاسترداد مع الذمم المدينة والضريبة المستحقة مع الذمم الدائنة.\nتُؤخذ مؤونة ضريبة الدخل وفقاً لقانون الضرائب "
            "اللبناني.\nتُقيَّد المؤونات عندما يكون على الشركة التزام حالي يمكن قياسه بشكل موثوق، ويخضع تعويض نهاية الخدمة لقانون العمل اللبناني وأنظمة "
            "الصندوق الوطني للضمان الاجتماعي."
        ),
        "Judgements and estimates": (
            "يتطلب إعداد البيانات المالية من الإدارة إجراء أحكام وتقديرات، لا سيما بشأن الخسائر الائتمانية المتوقعة على الذمم المدينة، وصافي القيمة "
            "القابلة للتحقق للمخزون، والعمر الإنتاجي للممتلكات والمعدات، والمؤونات. [استكمال الأحكام الخاصة بالشركة.]"
        ),
        "Share capital": "يبلغ رأس مال الشركة {share_capital}، مدفوع بالكامل. [تأكيد عدد الأسهم وقيمتها الاسمية وأي تغيير خلال السنة.]",
        "Income tax": (
            "تُحتسب ضريبة الدخل وفقاً لقانون ضريبة الدخل اللبناني على الربح الخاضع للضريبة عن الفترة، بعد إضافة الأعباء غير المقبولة ضريبياً. [إدراج "
            "التسوية بين الربح المحاسبي والربح الضريبي ومعدل الضريبة المطبق.]"
        ),
        "Currency and inflation": (
            "عملة التشغيل والعرض هي {basis}. تُحوَّل الأرصدة بالعملات الأخرى بالأسعار المسجلة في الدفاتر. [تقييم أثر الوضع الاقتصادي في لبنان وتعدد "
            "أسعار الصرف ومعيار المحاسبة الدولي 29 عند الاقتضاء.]"
        ),
        "Financial risk management": (
            "تتعرض الشركة لمخاطر الائتمان، لا سيما على الذمم المدينة التجارية والأرصدة لدى المصارف، ولمخاطر السيولة، ولمخاطر العملات على الأرصدة "
            "والعمليات بعملات غير {basis}، بما في ذلك أثر تعدد أسعار الصرف في لبنان. تتابع الإدارة هذه المخاطر بشكل منتظم. [استكمال سياسات الشركة "
            "والمبالغ الرئيسية المعرّضة.]"
        ),
        "Related parties and commitments": "[تعداد الأطراف ذات العلاقة (المساهمون، أعضاء مجلس الإدارة، الشركات الخاضعة لسيطرة مشتركة) والعمليات والأرصدة معهم، والالتزامات والمطلوبات المحتملة.]",
        "Events and going concern": "[وصف الأحداث اللاحقة لتاريخ البيانات المالية (المعيار المحاسبي الدولي 10) وتقييم استمرارية النشاط.]",
        "Additional disclosures": "[إضافة الإفصاحات الأخرى عند الاقتضاء: عقود الإيجار، إدارة رأس المال، إعادة تصنيف أرقام المقارنة.]",
        "Approval of the financial statements": "وافقت الإدارة على إصدار البيانات المالية بتاريخ {approval_date}.",
    },
}

AUDIT = {
    "fr": {
        "Addressee": "Aux actionnaires de {company}",
        "Opinion": (
            "Nous avons effectué l'audit des états financiers de {company} (la « Société »), qui comprennent l'état de la situation financière au "
            "{end_text}, l'état du résultat net et des autres éléments du résultat global, l'état des variations des capitaux propres et le tableau des "
            "flux de trésorerie pour l'{period_text} clos à cette date, ainsi que les notes annexes, y compris les informations significatives sur les "
            "méthodes comptables.\nÀ notre avis, les états financiers ci-joints donnent, dans tous leurs aspects significatifs, une image fidèle de la "
            "situation financière de la Société au {end_text}, ainsi que de sa performance financière et de ses flux de trésorerie pour l'{period_text} "
            "clos à cette date, conformément aux Normes internationales d'information financière (IFRS)."
        ),
        "Basis for opinion": (
            "Nous avons effectué notre audit conformément aux Normes internationales d'audit (ISA). Nos responsabilités en vertu de ces normes sont "
            "décrites dans la section « Responsabilités de l'auditeur à l'égard de l'audit des états financiers » du présent rapport. Nous sommes "
            "indépendants de la Société conformément au Code international de déontologie des professionnels comptables (Code de l'IESBA) et aux règles "
            "de déontologie applicables à l'audit des états financiers au Liban, et nous nous sommes acquittés de nos autres responsabilités "
            "déontologiques. Nous estimons que les éléments probants que nous avons obtenus sont suffisants et appropriés pour fonder notre opinion."
        ),
        "Going concern / key audit matters": "", "Other information": "",
        "Management and governance responsibilities": (
            "La direction est responsable de la préparation et de la présentation fidèle des états financiers conformément aux IFRS, ainsi que du "
            "contrôle interne qu'elle estime nécessaire pour permettre la préparation d'états financiers exempts d'anomalies significatives, que "
            "celles-ci résultent de fraudes ou d'erreurs.\nLors de la préparation des états financiers, il incombe à la direction d'évaluer la capacité "
            "de la Société à poursuivre son exploitation, de communiquer, le cas échéant, les questions relatives à la continuité d'exploitation et "
            "d'appliquer le principe comptable de continuité d'exploitation, sauf si la direction a l'intention de liquider la Société ou de cesser son "
            "activité, ou si aucune autre solution réaliste ne s'offre à elle.\nIl incombe aux responsables de la gouvernance de surveiller le processus "
            "d'information financière de la Société."
        ),
        "Auditor responsibilities": (
            "Nos objectifs sont d'obtenir l'assurance raisonnable que les états financiers pris dans leur ensemble sont exempts d'anomalies "
            "significatives, que celles-ci résultent de fraudes ou d'erreurs, et de délivrer un rapport contenant notre opinion. L'assurance raisonnable "
            "correspond à un niveau élevé d'assurance, qui ne garantit toutefois pas qu'un audit réalisé conformément aux normes ISA permettra toujours "
            "de détecter toute anomalie significative existante. Les anomalies peuvent résulter de fraudes ou d'erreurs et sont considérées comme "
            "significatives lorsqu'il est raisonnable de s'attendre à ce que, individuellement ou collectivement, elles puissent influer sur les "
            "décisions économiques que les utilisateurs prennent en se fondant sur ces états financiers.\nDans le cadre d'un audit réalisé conformément "
            "aux normes ISA, nous exerçons notre jugement professionnel et faisons preuve d'esprit critique tout au long de l'audit. Nous identifions et "
            "évaluons les risques d'anomalies significatives, prenons connaissance du contrôle interne pertinent pour l'audit, apprécions le caractère "
            "approprié des méthodes comptables et le caractère raisonnable des estimations comptables, concluons quant au caractère approprié de "
            "l'application par la direction du principe de continuité d'exploitation et évaluons la présentation d'ensemble, la structure et le contenu "
            "des états financiers.\nNous communiquons aux responsables de la gouvernance notamment l'étendue et le calendrier prévus des travaux d'audit "
            "et nos constatations importantes, y compris toute déficience importante du contrôle interne relevée au cours de notre audit."
        ),
        "Other legal and regulatory requirements": "",
        "Signature, address and report date": "{auditor_firm}\n{auditor_partner} - Licence n° {auditor_license}\n{auditor_address}\n{report_city}, le {report_date}",
    },
    "ar": {
        "Addressee": "إلى السادة مساهمي {company}",
        "Opinion": (
            "لقد دققنا البيانات المالية لـ{company} (\"الشركة\")، والتي تتضمن بيان المركز المالي كما في {end_text}، وبيان الربح أو الخسارة والدخل الشامل "
            "الآخر، وبيان التغيرات في حقوق الملكية، وبيان التدفقات النقدية عن {period_text} المنتهية بذلك التاريخ، والإيضاحات حول البيانات المالية، بما "
            "فيها المعلومات الهامة حول السياسات المحاسبية.\nفي رأينا، إن البيانات المالية المرفقة تُظهر بصورة عادلة، من جميع النواحي الجوهرية، المركز "
            "المالي للشركة كما في {end_text}، وأداءها المالي وتدفقاتها النقدية عن {period_text} المنتهية بذلك التاريخ، وفقاً للمعايير الدولية لإعداد "
            "التقارير المالية (IFRS)."
        ),
        "Basis for opinion": (
            "لقد قمنا بالتدقيق وفقاً لمعايير التدقيق الدولية (ISA). إن مسؤولياتنا وفقاً لهذه المعايير موضحة في فقرة \"مسؤوليات مدقق الحسابات عن تدقيق "
            "البيانات المالية\" من تقريرنا. نحن مستقلون عن الشركة وفقاً لقواعد السلوك المهني للمحاسبين الصادرة عن مجلس المعايير الدولية لأخلاقيات "
            "المحاسبين (IESBA)، وللمتطلبات الأخلاقية المتعلقة بتدقيق البيانات المالية في لبنان، وقد التزمنا بمسؤولياتنا الأخلاقية الأخرى وفقاً لهذه "
            "المتطلبات. نعتقد أن أدلة التدقيق التي حصلنا عليها كافية ومناسبة لتوفير أساس لرأينا."
        ),
        "Going concern / key audit matters": "", "Other information": "",
        "Management and governance responsibilities": (
            "إن الإدارة مسؤولة عن إعداد البيانات المالية وعرضها بصورة عادلة وفقاً للمعايير الدولية لإعداد التقارير المالية، وعن نظام الرقابة الداخلية "
            "الذي تراه ضرورياً لإعداد بيانات مالية خالية من الأخطاء الجوهرية، سواء كانت ناتجة عن احتيال أو خطأ.\nعند إعداد البيانات المالية، تكون "
            "الإدارة مسؤولة عن تقييم قدرة الشركة على الاستمرار في النشاط، والإفصاح، حسب الاقتضاء، عن الأمور المتعلقة بالاستمرارية، واستخدام أساس "
            "الاستمرارية في المحاسبة، ما لم تكن الإدارة تنوي تصفية الشركة أو وقف أعمالها أو لم يكن لديها بديل واقعي سوى ذلك.\nإن المكلفين بالحوكمة "
            "مسؤولون عن الإشراف على عملية إعداد التقارير المالية للشركة."
        ),
        "Auditor responsibilities": (
            "تتمثل أهدافنا في الحصول على تأكيد معقول بأن البيانات المالية ككل خالية من الأخطاء الجوهرية، سواء كانت ناتجة عن احتيال أو خطأ، وإصدار تقرير "
            "المدقق الذي يتضمن رأينا. إن التأكيد المعقول هو مستوى عالٍ من التأكيد، ولكنه لا يضمن أن التدقيق الذي يتم وفقاً لمعايير التدقيق الدولية سيكشف "
            "دائماً عن الخطأ الجوهري عند وجوده. قد تنشأ الأخطاء عن احتيال أو خطأ وتُعتبر جوهرية إذا كان من المتوقع بشكل معقول أن تؤثر، منفردة أو مجتمعة، "
            "على القرارات الاقتصادية التي يتخذها المستخدمون بناءً على هذه البيانات المالية.\nكجزء من التدقيق وفقاً لمعايير التدقيق الدولية، نمارس الحكم "
            "المهني ونحافظ على الشك المهني طوال عملية التدقيق. نقوم بتحديد وتقييم مخاطر الأخطاء الجوهرية، والاطلاع على نظام الرقابة الداخلية ذي الصلة "
            "بالتدقيق، وتقييم ملاءمة السياسات المحاسبية المتبعة ومعقولية التقديرات المحاسبية، والاستنتاج حول ملاءمة استخدام الإدارة لأساس الاستمرارية، "
            "وتقييم العرض العام للبيانات المالية وهيكلها ومحتواها.\nنتواصل مع المكلفين بالحوكمة بشأن أمور منها نطاق التدقيق وتوقيته المخطط له والنتائج "
            "الهامة للتدقيق، بما في ذلك أي أوجه قصور هامة في نظام الرقابة الداخلية نحددها خلال تدقيقنا."
        ),
        "Other legal and regulatory requirements": "",
        "Signature, address and report date": "{auditor_firm}\n{auditor_partner} - رقم الإجازة {auditor_license}\n{auditor_address}\n{report_city}، في {report_date}",
    },
}


INFO_LABELS = {  # what to complete, when the company / auditor information was not entered
    "fr": {"legal_form": "Forme juridique (ex. S.A.L., S.A.R.L.)", "cr_number": "Numéro du registre du commerce", "incorporation_date": "Date de constitution",
           "tax_number": "Numéro fiscal (MoF)", "activities": "Activités principales", "shareholders": "Actionnaires / associés",
           "directors": "Administrateurs / gérants", "share_capital": "Capital social (montant)", "approval_date": "Date d'approbation",
           "auditor_firm": "Cabinet d'audit", "auditor_partner": "Associé signataire", "auditor_license": "Numéro de licence (LACPA)",
           "auditor_address": "Adresse de l'auditeur", "report_city": "Ville du rapport", "report_date": "Date du rapport de l'auditeur",
           "company": "Nom de la société"},
    "ar": {"legal_form": "الشكل القانوني (ش.م.ل.، ش.م.م.)", "cr_number": "رقم السجل التجاري", "incorporation_date": "تاريخ التأسيس",
           "tax_number": "الرقم المالي", "activities": "النشاطات الرئيسية", "shareholders": "المساهمون / الشركاء",
           "directors": "أعضاء مجلس الإدارة / المدراء", "share_capital": "رأس المال (المبلغ)", "approval_date": "تاريخ الموافقة على الإصدار",
           "auditor_firm": "مكتب التدقيق", "auditor_partner": "الشريك الموقّع", "auditor_license": "رقم الإجازة (LACPA)",
           "auditor_address": "عنوان مدقق الحسابات", "report_city": "مدينة التقرير", "report_date": "تاريخ تقرير مدقق الحسابات",
           "company": "إسم الشركة"},
}


COVER = {
    "en": {"title": "FINANCIAL STATEMENTS", "sub": "AND INDEPENDENT AUDITOR'S REPORT", "contents": "CONTENTS", "page": "Page",
           "audit": "Independent auditor's report", "position": "Statement of Financial Position",
           "profit": "Statement of Profit or Loss and Other Comprehensive Income", "equity": "Statement of Changes in Equity",
           "cash": "Statement of Cash Flows", "notes": "Notes to the financial statements",
           "sheets": {"audit": "Auditor's Report", "position": "Financial Position", "profit": "Profit or Loss", "equity": "Changes in Equity",
                      "cash": "Cash Flows", "notes": "Notes", "review": "Review Points", "cover": "Cover"}},
    "fr": {"title": "ÉTATS FINANCIERS", "sub": "ET RAPPORT DE L'AUDITEUR INDÉPENDANT", "contents": "SOMMAIRE", "page": "Page",
           "audit": "Rapport de l'auditeur indépendant", "position": "État de la situation financière",
           "profit": "État du résultat net et des autres éléments du résultat global", "equity": "État des variations des capitaux propres",
           "cash": "Tableau des flux de trésorerie", "notes": "Notes annexes aux états financiers",
           "sheets": {"audit": "Rapport d'audit", "position": "Situation financière", "profit": "Résultat", "equity": "Capitaux propres",
                      "cash": "Flux de trésorerie", "notes": "Notes", "review": "Points de revue", "cover": "Couverture"}},
    "ar": {"title": "البيانات المالية", "sub": "وتقرير مدقق الحسابات المستقل", "contents": "المحتويات", "page": "صفحة",
           "audit": "تقرير مدقق الحسابات المستقل", "position": "بيان المركز المالي", "profit": "بيان الربح أو الخسارة والدخل الشامل الآخر",
           "equity": "بيان التغيرات في حقوق الملكية", "cash": "بيان التدفقات النقدية", "notes": "إيضاحات حول البيانات المالية",
           "sheets": {"audit": "تقرير التدقيق", "position": "المركز المالي", "profit": "الربح أو الخسارة", "equity": "حقوق الملكية",
                      "cash": "التدفقات النقدية", "notes": "الإيضاحات", "review": "نقاط المراجعة", "cover": "الغلاف"}},
}
TITLE_LANGUAGE = {"Financial Statements,": "en", "États financiers,": "fr", "البيانات المالية والإيضاحات": "ar"}


def language_of(title):
    return next((language for start, language in TITLE_LANGUAGE.items() if str(title or "").startswith(start)), "en")


TEXTS.update({
    'Financial Statement Reconciliation': ('Rapprochement des états financiers','مطابقة البيانات المالية'),
    'FINANCIAL STATEMENT RECONCILIATION (preparer only)': ('RAPPROCHEMENT DES ÉTATS FINANCIERS (préparateur uniquement)','مطابقة البيانات المالية (لمعدّ التقرير فقط)'),
    'Check - expected zero': ('Contrôle - zéro attendu','فحص - المتوقع صفر'),
    'Financial position: assets less equity and liabilities': ('Situation financière : actifs moins capitaux propres et passifs','المركز المالي: الموجودات ناقص حقوق الملكية والمطلوبات'),
    'Cash: closing less opening and reported movement': ('Trésorerie : clôture moins ouverture et variation présentée','النقد: الختامي ناقص الافتتاحي والحركة المعروضة'),
    'Unmapped accounts: gross absolute balance': ('Comptes non classés : soldes absolus bruts','الحسابات غير المصنّفة: مجموع الأرصدة المطلقة'),
})

def translator(language):
    """t(english_text, **values): the text in the chosen language (English when there is no translation)."""
    index = {"fr": 0, "ar": 1}.get(language)
    def t(text, **values):
        out = TEXTS[text][index] if index is not None and text in TEXTS else text
        for key, value in values.items(): out = out.replace("{" + key + "}", str(value))
        return out
    return t
