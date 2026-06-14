import os

# Repository root. Runtime code lives in freecad/BulletPhysics in the modern
# addon layout, while resources and metadata remain at the addon root.
MOD_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
