"""
Алгоритм раскраски попытки (🟩🟨⬜), корректно обрабатывающий повторяющиеся буквы —
классическая двухпроходная реализация Wordle.
"""


def check_guess(guess: str, answer: str) -> list[str]:
    """
    Возвращает список статусов длиной len(answer): "correct" | "present" | "absent".
    guess и answer должны быть одной длины и в нижнем регистре.
    """
    guess = guess.lower()
    answer = answer.lower()
    n = len(answer)
    result = ["absent"] * n

    answer_letters = list(answer)

    # Первый проход — точные совпадения
    for i in range(n):
        if guess[i] == answer[i]:
            result[i] = "correct"
            answer_letters[i] = None  # буква "использована"

    # Второй проход — буква есть, но не на своём месте
    for i in range(n):
        if result[i] == "correct":
            continue
        if guess[i] in answer_letters:
            result[i] = "present"
            answer_letters[answer_letters.index(guess[i])] = None

    return result


def is_solved(statuses: list[str]) -> bool:
    return all(s == "correct" for s in statuses)
