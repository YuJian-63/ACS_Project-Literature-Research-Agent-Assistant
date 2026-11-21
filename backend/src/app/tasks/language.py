import re


def answer_language_instruction(question: str | None) -> str:
    if not question or not question.strip():
        return "No user question was supplied; answer in Chinese. Keep source quotations verbatim."
    return (
        "Answer in the same language as the user question, not the language of these instructions, "
        "the interface or the selected papers. For mixed-language questions use the main natural language, "
        "not isolated technical terms. Keep source quotations verbatim."
    )


def uses_english_labels(question: str | None) -> bool:
    return bool(question and question.strip() and not re.search(r"[\u3400-\u9fff]", question))
