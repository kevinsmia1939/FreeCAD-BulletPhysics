import os

# Importable module — Python's normal import sets __file__ here even when
# FreeCAD exec()-loads InitGui.py without __file__.
MOD_PATH = os.path.dirname(os.path.abspath(__file__))
