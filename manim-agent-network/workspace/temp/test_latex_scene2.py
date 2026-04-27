from manim import *

class Scene1(Scene):
    def construct(self):
        formula = MathTex(r"\frac{1}{2}")
        self.add(formula)
        self.wait()