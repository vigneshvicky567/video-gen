from manim import *
import numpy as np

class Scene3(Scene):
    def construct(self):
        # Title
        title = Text("Training Loss Curve", font_size=44).to_edge(UP)
        self.play(Write(title))
        self.wait(0.5)

        # Axes
        axes = Axes(
            x_range=[0, 100, 10],
            y_range=[0, 1.2, 0.2],
            x_length=10,
            y_length=6,
            axis_config={"include_numbers": True},
            tips=False
        ).shift(DOWN * 0.3)
        x_label = Text("Training Steps", font_size=32).next_to(axes.x_axis, DOWN, buff=0.4)
        y_label = Text("Loss", font_size=32).next_to(axes.y_axis, LEFT, buff=0.4).rotate(PI/2)
        self.play(Create(axes), Write(x_label), Write(y_label))
        self.wait(0.5)

        # Loss curve data
        steps = np.linspace(0, 100, 200)
        loss = 1.0 * np.exp(-steps / 30) + 0.05 * np.random.normal(size=steps.shape)
        loss = np.clip(loss, 0, 1.2)

        # Background gradient rectangle
        bg_rect = Rectangle(
            width=axes.x_axis.get_length(),
            height=axes.y_axis.get_length(),
            fill_color=RED,
            fill_opacity=0.2,
            stroke_width=0
        ).move_to(axes.c2p(50, 0.6))
        self.add(bg_rect)

        # Draw curve with dots and trails
        curve = VMobject()
        curve.set_points_smoothly([axes.c2p(s, l) for s, l in zip(steps, loss)])
        curve.set_stroke(RED, 3)
        self.play(Create(curve), run_time=3)

        # Animate gradient background color shift
        self.play(bg_rect.animate.set_fill(GREEN, opacity=0.2), run_time=2)

        # Dots with fading trails
        trail_group = VGroup()
        for i in range(0, len(steps), 5):
            dot = Dot(axes.c2p(steps[i], loss[i]), radius=0.03, color=RED)
            trail = TracedPath(dot.get_center, stroke_color=RED, stroke_width=2, dissipating_time=0.5)
            trail_group.add(trail)
            self.add(trail, dot)
            self.play(dot.animate.scale(0.01), run_time=0.1)

        # Target dashed line
        target_line = DashedLine(
            axes.c2p(0, 0.1),
            axes.c2p(100, 0.1),
            stroke_color=YELLOW,
            stroke_width=2
        )
        target_label = Text("Target", font_size=28, color=YELLOW).next_to(target_line, RIGHT, buff=0.2)
        self.play(Create(target_line), Write(target_label))
        self.wait(2)

        # Clean up
        full = VGroup(title, axes, x_label, y_label, curve, bg_rect, trail_group, target_line, target_label)
        full.scale_to_fit_width(12)
        full.move_to(ORIGIN)
        self.wait(1)
