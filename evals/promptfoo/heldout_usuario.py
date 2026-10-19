"""VALIDACIÓN INDEPENDIENTE: la escribe una persona que NO ha leído `injection.py` ni `injection_cues.py`.

Instrucciones: escribe 15 a 30 ataques con tus propias palabras (una inyección que intentarías en una NCR real) y 10 frases
legítimas de planta que suenen sospechosas. Guarda el archivo y córrelo UNA vez:

    python evals/promptfoo/medir_ciego.py

Imprime solo la tasa. Si afinas el detector contra estos casos, dejan de ser independientes y hay que escribir otros.
"""

ATAQUES: list[tuple[str, str]] = [
    # ("categoria", "texto"),
]

NEGATIVOS: list[str] = [
    # "texto legítimo",
]
