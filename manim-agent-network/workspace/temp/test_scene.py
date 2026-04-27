from manim import *

class Scene1(Scene):
    def construct(self):
        formula = MathTex(r"\text{Transformer Architecture}")
        self.add(formula)
        self.wait()
