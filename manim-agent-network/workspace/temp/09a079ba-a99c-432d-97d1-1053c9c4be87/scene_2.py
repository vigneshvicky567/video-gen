from manim import *
import numpy as np

class Scene2(Scene):
    def construct(self):
        # Title
        title = Text("Bumpy Loss Landscape", font_size=40).to_edge(UP)
        self.play(Write(title))
        self.wait(0.5)

        # Axes and curve
        axes = Axes(x_range=[-2, 2], y_range=[-1, 3], x_length=8, y_length=5).move_to(DOWN*0.5)
        curve = axes.plot(lambda x: x**4 - 3*x**2 + 2, color=BLUE, stroke_width=3)
        self.play(Create(axes), Create(curve))
        self.wait(0.5)

        # Red sphere on curve at x=1.8
        x0 = 1.8
        y0 = x0**4 - 3*x0**2 + 2
        sphere = Dot(axes.c2p(x0, y0), color=RED, radius=0.1)
        self.play(FadeIn(sphere))
        self.wait(0.5)

        # Slow pan across curve
        self.play(axes.animate.shift(LEFT*2), curve.animate.shift(LEFT*2), sphere.animate.shift(LEFT*2), run_time=3)
        self.wait(0.5)

        # Pulse minima twice
        min_x = np.sqrt(1.5)
        min_y = min_x**4 - 3*min_x**2 + 2
        highlight = Circle(radius=0.3, color=YELLOW, stroke_width=6).move_to(axes.c2p(min_x, min_y))
        for _ in range(2):
            self.play(highlight.animate.scale(1.5).set_opacity(0), run_time=0.7)
            self.play(highlight.animate.scale(1/1.5).set_opacity(1), run_time=0.7)
        self.wait(2)