from manim import *

class Scene1(Scene):
    def construct(self):
        formula = MathTex(r"x^2 + y^2 = z^2")
        self.add(formula)
        self.wait()