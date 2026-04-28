from manim import *
import numpy as np

class Scene3(Scene):
    def construct(self):
        # Title
        title = Text("Gradient Descent", font_size=44).to_edge(UP)
        self.play(Write(title))
        self.wait(0.5)

        # Axes & curve
        axes = Axes(x_range=[-3, 3], y_range=[0, 9], x_length=8, y_length=5).move_to(DOWN*0.5)
        curve = axes.plot(lambda x: x**2, color=BLUE)
        self.play(Create(axes), Create(curve))
        self.wait(0.5)

        # Step counter (top-right)
        counter = Text("Step 0", font_size=36).to_edge(UR)
        self.play(FadeIn(counter))

        # Initial point
        x0 = 2.0
        dot = Dot(axes.c2p(x0, x0**2), color=RED)
        self.play(FadeIn(dot))
        self.wait(0.5)

        # Gradient descent parameters
        eta = 0.3
        for step in [1, 2]:
            # Compute gradient
            grad = 2 * x0  # d/dx x^2 = 2x
            tangent = axes.plot(lambda x: 2*x0*(x - x0) + x0**2, x_range=[x0-1, x0+1], color=YELLOW)
            self.play(Create(tangent))
            self.wait(0.5)

            # Arrow label
            arrow = Arrow(
                start=axes.c2p(x0, x0**2),
                end=axes.c2p(x0 - eta*grad, (x0 - eta*grad)**2),
                buff=0,
                color=GREEN
            )
            label = MathTex(r"-\eta\cdot\nabla L", font_size=32).next_to(arrow, UP)
            self.play(GrowArrow(arrow), FadeIn(label))
            self.wait(0.5)

            # Move dot
            x1 = x0 - eta*grad
            self.play(
                dot.animate.move_to(axes.c2p(x1, x1**2)),
                run_time=1.5
            )
            x0 = x1

            # Update counter
            new_counter = Text(f"Step {step}", font_size=36).to_edge(UR)
            self.play(Transform(counter, new_counter))

            # Fade out tangent & arrow
            self.play(FadeOut(tangent), FadeOut(arrow), FadeOut(label))
            self.wait(0.5)

        self.wait(2)