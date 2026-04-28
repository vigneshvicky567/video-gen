from manim import *
import numpy as np

class Scene4(Scene):
    def construct(self):
        # Title
        title = Text("Each step shrinks the loss until we bottom out", font_size=36).to_edge(UP)
        self.play(Write(title))
        self.wait(0.5)

        # Axes and loss curve
        axes = Axes(x_range=[-4,4], y_range=[0,4], x_length=10, y_length=5).move_to(DOWN*0.5)
        curve = axes.plot(lambda x: 0.2*(x**4 - 4*x**2 + 0.5*x + 8), color=BLUE, stroke_width=3)
        self.play(Create(axes), Create(curve))
        self.wait(0.5)

        # Sphere (dot) and loss label
        sphere = Dot(axes.c2p(-3.5, 3.5), color=RED, radius=0.12)
        loss_label = MathTex("\text{Loss: }", "3.5", font_size=32).next_to(sphere, UP*1.5)
        self.play(FadeIn(sphere), FadeIn(loss_label))
        self.wait(0.5)

        # Trail container
        trail = VGroup()
        self.add(trail)

        # Path points (pre-computed)
        xs = np.linspace(-3.5, 0.0, 50)
        ys = [0.2*(x**4 - 4*x**2 + 0.5*x + 8) for x in xs]
        points = [axes.c2p(x, y) for x, y in zip(xs, ys)]

        # Animate descent
        for i, (x, y) in enumerate(zip(xs, ys)):
            # Update sphere
            new_pos = axes.c2p(x, y)
            self.play(
                sphere.animate.move_to(new_pos),
                Transform(loss_label[1], MathTex(f"{y:.2f}", font_size=32).move_to(loss_label[1])),
                run_time=0.05,
                rate_func=linear
            )
            # Add faint red dot to trail
            trail.add(Dot(new_pos, color=RED, fill_opacity=0.2, radius=0.04))

        # Flash green checkmark
        check = Tex(r"\checkmark", color=GREEN, font_size=64).next_to(sphere, DOWN*1.5)
        self.play(Flash(check, color=GREEN))
        self.play(FadeIn(check))
        self.wait(1)

        # Zoom out to full curve
        full = VGroup(axes, curve, trail, sphere, loss_label, check)
        self.play(full.animate.scale(0.7).move_to(ORIGIN))
        self.wait(2)
