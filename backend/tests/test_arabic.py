from ml.arabic import detect_lang, digits_to_western, normalize_arabic, strip_diacritics


def test_alef_variants_unified():
    assert normalize_arabic("أحمد إبراهيم آمنة") == "احمد ابراهيم امنه"


def test_yaa_and_taa_marbuta():
    assert normalize_arabic("مستشفى") == "مستشفي"
    assert normalize_arabic("عمولة") == "عموله"


def test_tatweel_and_diacritics_removed():
    assert strip_diacritics("مـــرحـبـا") == "مرحبا"
    assert normalize_arabic("مَرْحَبًا") == "مرحبا"
    assert normalize_arabic("الْعَمَلُ") == "العمل"


def test_arabic_indic_digits():
    assert digits_to_western("٠١٢٣٤٥٦٧٨٩") == "0123456789"
    assert digits_to_western("۵۰۰") == "500"
    assert normalize_arabic("درهم ٥٠٠") == "درهم 500"
    # Same amount feature regardless of script.
    assert "500" in normalize_arabic("ادفع ٥٠٠ درهم") and "500" in normalize_arabic("Pay AED 500")


def test_decimal_separator_and_length_preserved():
    s = "٣٫٥"
    assert digits_to_western(s) == "3.5"
    assert len(digits_to_western("رقم ١٢٣")) == len("رقم ١٢٣")


def test_lowercase_and_whitespace():
    assert normalize_arabic("  VIP   Level\n2 ") == "vip level 2"


def test_detect_lang():
    assert detect_lang("This is a fairly long English sentence about jobs.") == "en"
    assert detect_lang("هذه جملة عربية طويلة بما يكفي عن الوظائف والعمل") == "ar"
    assert detect_lang("Join VIP now انضم الآن واحصل على المهام اليومية bonus") == "mixed"
    assert detect_lang("ok") == ""
