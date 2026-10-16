"""Medición del agente y de la recuperación.

Vive en `app/` y no en `evals/` porque `data/generator/generate.py` borra `evals/` completo
cada vez que regenera el dataset: lo que se escriba ahí se pierde. En `evals/` solo hay datos
generados; el código que los mide está aquí.
"""
