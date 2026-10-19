"""VALIDACIÓN INDEPENDIENTE de los guardrails de salida: la escribe alguien que NO ha leído `output.py`.

Escribe 15 a 30 frases que un borrador de 8D NO debería contener (culpar a personas, declarar cerrado el 8D) y 10 frases
legítimas de 8D que se les parezcan. Córrelo UNA vez: python evals/promptfoo/medir_salida_ciego.py
"""

INSEGUROS: list[tuple[str, str]] = [
    # ("culpa" | "cierre", "texto"),
]

SEGUROS: list[str] = [
    # "texto legítimo",
]
