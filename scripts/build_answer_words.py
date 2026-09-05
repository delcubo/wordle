"""
Пересобирает api/data/answer_words.txt (единственный словарь, которым
пользуется приложение — и для слова дня, и для проверки попыток игрока) из
исходного широкого словаря scripts/data/russian_words.txt — отбирает только
существительные в именительном падеже (без словоформ, имён собственных,
других частей речи), чтобы игра не принимала и не загадывала мусор.

Не часть рантайма приложения — запускается вручную при обновлении исходного
словаря. Нужен pymorphy3 (не входит в requirements.txt, там он не нужен):

    pip install pymorphy3 pymorphy3-dicts-ru
    python scripts/build_answer_words.py

Логика отбора слова W: среди всех разборов pymorphy для W есть хотя бы один,
где одновременно
  - часть речи — существительное (NOUN);
  - падеж — именительный (nomn);
  - словарная форма (normal_form) совпадает с самим словом — то есть W уже
    стоит в начальной форме. Для обычных существительных начальная форма — это
    именительный падеж единственного числа, поэтому проверка одновременно
    отсекает все словоформы (падежные и числовые) без отдельной проверки
    "число = единственное" — иначе отсеялись бы pluralia tantum вроде
    "ножницы", у которых единственного числа не существует, а начальная форма
    и так именительный падеж множественного;
  - разбор помечен как известный словарю (is_known) — отсекает "угаданные"
    эвристикой формы для отсутствующих в словаре слов;
  - среди тегов разбора нет признаков имени собственного (Name/Surn/Patr/
    Geox/Orgn/Trad) или аббревиатуры (Abbr).

Фильтр не идеален: изредка проходят топонимы/термины, которые pymorphy не
пометил как собственные (словарь OpenCorpora неполон), и остаются архаичные
или редкие слова — это всё ещё настоящие существительные, просто нечастые.
Для более строгого отбора можно дополнительно скрестить результат со списком
частотности слов, но это отдельная задача.
"""
import os

import pymorphy3

_HERE = os.path.dirname(__file__)
_SOURCE_PATH = os.path.join(_HERE, "data", "russian_words.txt")
_TARGET_PATH = os.path.join(_HERE, "..", "api", "data", "answer_words.txt")

PROPER_NOUN_TAGS = {"Name", "Surn", "Patr", "Geox", "Orgn", "Trad", "Abbr"}


def is_clean_nominative_noun(morph: pymorphy3.MorphAnalyzer, word: str) -> bool:
    for parse in morph.parse(word):
        if not parse.is_known:
            continue
        tag = parse.tag
        if tag.POS != "NOUN":
            continue
        if tag.case != "nomn":
            continue
        if parse.normal_form != word:
            continue
        if any(grammeme in tag for grammeme in PROPER_NOUN_TAGS):
            continue
        return True
    return False


def main():
    morph = pymorphy3.MorphAnalyzer()

    with open(_SOURCE_PATH, encoding="utf-8") as f:
        words = [w.strip() for w in f if w.strip()]

    answer_words = [w for w in words if is_clean_nominative_noun(morph, w)]

    with open(_TARGET_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(answer_words) + "\n")

    print(f"{len(words)} слов на входе -> {len(answer_words)} в списке ответов")


if __name__ == "__main__":
    main()
