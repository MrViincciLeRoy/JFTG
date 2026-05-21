import re
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


GENDER_MALE = ["he ", "his ", "him ", "male", "man ", "men ", "boy ", "mr "]
GENDER_FEMALE = ["she ", "her ", "hers", "female", "woman ", "women ", "girl ", "ms ", "mrs "]

AGE_PAT = re.compile(r"\b(\d{1,2})[- ]?year[s]?[- ]?old\b", re.I)


def extract_character(story: dict, case: dict) -> dict:
    accused_name = (case.get("accused") or "").strip()
    text = " ".join([
        story.get("background", ""),
        story.get("incident", ""),
        story.get("hook", ""),
        case.get("full_text", "")[:2000],
    ]).lower()

    gender = _detect_gender(text)
    age = _detect_age(text)
    province = case.get("province", "South Africa")

    description = _build_description(accused_name, gender, age, province, text)

    return {
        "name": accused_name,
        "gender": gender,
        "age": age,
        "province": province,
        "description": description,
    }


def _detect_gender(text: str) -> str:
    male_score = sum(text.count(w) for w in GENDER_MALE)
    female_score = sum(text.count(w) for w in GENDER_FEMALE)
    if female_score > male_score:
        return "female"
    return "male"


def _detect_age(text: str) -> str:
    m = AGE_PAT.search(text)
    if m:
        return m.group(1)
    return ""


def _build_description(name: str, gender: str, age: str, province: str, text: str) -> str:
    gender_noun = "man" if gender == "male" else "woman"
    age_str = f"{age}-year-old " if age else ""

    skin_hint = ""
    if any(w in text for w in ["black south african", "african accused", "zulu", "xhosa", "sotho", "tswana", "venda", "tsonga"]):
        skin_hint = "Black South African, "
    elif any(w in text for w in ["white accused", "afrikaner", "boer"]):
        skin_hint = "White South African, "
    elif any(w in text for w in ["coloured accused", "cape coloured"]):
        skin_hint = "Coloured South African, "
    elif any(w in text for w in ["indian accused", "tamil", "gujarati"]):
        skin_hint = "Indian South African, "

    base = f"{skin_hint}{age_str}{gender_noun} from {province}, South Africa"

    clothing = "wearing casual South African street clothing"
    if "prison" in text or "imprisonment" in text:
        clothing = "wearing a grey prison uniform"

    return f"{base}, {clothing}, realistic face, consistent character"