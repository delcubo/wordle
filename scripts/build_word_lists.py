"""
Собирает словари для слов разной длины (5, 6, 7 букв) прямо из морфологического
словаря pymorphy3 (OpenCorpora) — без внешних списков слов:

  api/data/valid_<N>.txt    — все допустимые попытки: существительные в начальной
                              форме (то же правило, что в build_answer_words.py)
  api/data/answers_<N>.txt  — слова, которые система может загадать: подмножество
                              допустимых, отобранное строже (см. is_good_answer) и
                              по частоте слова (wordfreq); только для N != 5 — для 5
                              букв ответами остаётся api/data/answer_words.txt

Не часть рантайма приложения — запускается вручную. Нужны пакеты, которых нет в
requirements.txt:

    pip install pymorphy3 pymorphy3-dicts-ru wordfreq
    python scripts/build_word_lists.py --lengths 5 6 7

Правила отбора:
  Допустимая попытка (valid) — хотя бы один разбор pymorphy, где слово: известно
  словарю, существительное, именительный падеж, словарная форма совпадает с самим
  словом, нет признаков имени собственного/аббревиатуры.

  Ответ (answers) — допустимое слово, у которого дополнительно:
    - частота по wordfreq (шкала Zipf) не ниже --min-zipf (по умолчанию 2.5) —
      без этого около 70% ответов были бы редкими словами;
    - главный (самый вероятный) разбор — существительное, а не прилагательное,
      глагол и т.п. ("военный", "красный", "чайная" отсеиваются);
    - главный разбор — не имя собственное и доля разборов-имён не больше половины
      ("гордон", "стелла", "юпитер" отсеиваются).
  Строгость иногда отсекает и обычные слова с омонимом-именем ("планка",
  "султан") — они остаются в допустимых попытках, а в ответы при желании
  добавляются вручную через api/data/answer_words_extra.txt.

Лицензия данных: словарь OpenCorpora распространяется под CC BY-SA 3.0, данные
wordfreq — по своим лицензиям; производные списки — того же рода, что и уже
используемый api/data/answer_words.txt.
"""
import argparse
import os

import pymorphy3

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_HERE, "..", "api", "data")

PROPER_TAGS = {"Name", "Surn", "Patr", "Geox", "Orgn", "Trad", "Abbr"}
SUPPORTED_LENGTHS = (5, 6, 7)
DEFAULT_MIN_ZIPF = 2.5


def _has_proper(parse) -> bool:
    return any(grammeme in parse.tag for grammeme in PROPER_TAGS)


def is_clean_noun(morph: pymorphy3.MorphAnalyzer, word: str) -> bool:
    """Допустимая попытка: чистое существительное в начальной форме."""
    for parse in morph.parse(word):
        if not parse.is_known:
            continue
        tag = parse.tag
        if tag.POS == "NOUN" and tag.case == "nomn" and parse.normal_form == word and not _has_proper(parse):
            return True
    return False


def is_good_answer(morph: pymorphy3.MorphAnalyzer, word: str) -> bool:
    """Строгий отбор для ответов: по главному разбору это обычное существительное."""
    parses = [p for p in morph.parse(word) if p.is_known]
    if not parses:
        return False
    top = parses[0]
    total = sum(p.score for p in parses) or 1
    proper_share = sum(p.score for p in parses if _has_proper(p)) / total
    if _has_proper(top) or proper_share >= 0.5:
        return False
    return top.tag.POS == "NOUN"


def candidate_words(morph: pymorphy3.MorphAnalyzer, length: int) -> list[str]:
    """Все словоформы словаря заданной длины, состоящие только из букв."""
    return sorted({w for w in morph.dictionary.words.keys() if len(w) == length and w.isalpha()})


def write_list(path: str, words: list[str]) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(words) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Сборка словарей для слов из 5, 6 и 7 букв")
    parser.add_argument("--lengths", type=int, nargs="+", default=list(SUPPORTED_LENGTHS))
    parser.add_argument("--min-zipf", type=float, default=DEFAULT_MIN_ZIPF, help="порог частоты для ответов (Zipf)")
    parser.add_argument("--out", default=_DATA_DIR, help="папка для файлов (по умолчанию api/data)")
    args = parser.parse_args()

    from wordfreq import zipf_frequency  # нужен только при сборке

    morph = pymorphy3.MorphAnalyzer()
    for length in args.lengths:
        if length not in SUPPORTED_LENGTHS:
            raise SystemExit(f"Длина {length} не поддерживается (доступно: {SUPPORTED_LENGTHS})")
        valid = [w for w in candidate_words(morph, length) if is_clean_noun(morph, w)]
        write_list(os.path.join(args.out, f"valid_{length}.txt"), valid)
        print(f"{length} букв: допустимых попыток {len(valid)}")
        if length == 5:
            continue  # для 5 букв ответы — прежний api/data/answer_words.txt
        answers = [w for w in valid if zipf_frequency(w, "ru") >= args.min_zipf and is_good_answer(morph, w)]
        write_list(os.path.join(args.out, f"answers_{length}.txt"), answers)
        print(f"{length} букв: ответов {len(answers)} (порог частоты Zipf >= {args.min_zipf})")


if __name__ == "__main__":
    main()
