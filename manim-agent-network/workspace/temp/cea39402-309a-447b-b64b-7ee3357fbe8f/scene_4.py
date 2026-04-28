from manim import *
import numpy as np

class Scene4(Scene):
    def construct(self):
        # 1. Title
        title = Text("Back-Propagation", font_size=44).to_edge(UP)
        self.play(Write(title))
        self.wait(0.5)

        # 2. Split screen layout
        left_group = VGroup()
        right_group = VGroup()

        # --- LEFT: Prediction vs Truth bar chart ---
        left_label = Text("Prediction vs Truth", font_size=32).next_to(title, DOWN, buff=0.6).shift(LEFT*3.5)
        left_group.add(left_label)

        bar_axes = Axes(
            x_range=[0, 3],
            y_range=[0, 1.2],
            x_length=4,
            y_length=3,
            tips=False
        )
        bar_axes.shift(LEFT*3.5 + DOWN*0.5)

        pred_bar = Rectangle(width=0.8, height=0.7, color=BLUE, fill_opacity=0.8).move_to(bar_axes.c2p(1, 0.35))
        truth_bar = Rectangle(width=0.8, height=1.0, color=GREEN, fill_opacity=0.8).move_to(bar_axes.c2p(2, 0.5))

        pred_label = Text("Pred", font_size=24).next_to(pred_bar, DOWN, buff=0.1)
        truth_label = Text("Truth", font_size=24).next_to(truth_bar, DOWN, buff=0.1)

        left_group.add(bar_axes, pred_bar, truth_bar, pred_label, truth_label)

        # --- RIGHT: Loss curve ---
        right_label = Text("Loss Curve", font_size=32).next_to(title, DOWN, buff=0.6).shift(RIGHT*3.5)
        right_group.add(right_label)

        loss_axes = Axes(
            x_range=[0, 5],
            y_range=[0, 3.5],
            x_length=4,
            y_length=3,
            tips=False
        )
        loss_axes.shift(RIGHT*3.5 + DOWN*0.5)

        loss_curve = loss_axes.plot_line_graph(
            x_values=np.linspace(0, 5, 100),
            y_values=np.linspace(3.2, 0.5, 100),
            line_color=BLUE,
            stroke_width=3
        )

        right_group.add(loss_axes, loss_curve)

        # Combine and scale
        full = VGroup(left_group, right_group)
        full.scale_to_fit_width(12)
        full.move_to(ORIGIN)
        self.play(FadeIn(full))
        self.wait(1)

        # 3. Network zoom back and weight updates
        network_group = VGroup()
        layers = [3, 4, 2, 1]
        spacing = 2.5
        neurons = []
        for i, size in enumerate(layers):
            col = VGroup(*[Circle(radius=0.2, color=WHITE, stroke_width=2) for _ in range(size)])
            col.arrange(DOWN, buff=0.4)
            col.shift(LEFT*3 + RIGHT*i*spacing)
            neurons.append(col)
            network_group.add(col)

        # Create edges with arrows for weights
        edges = VGroup()
        arrows = []
        for i in range(len(layers)-1):
            for src in neurons[i]:
                for dst in neurons[i+1]:
                    line = Line(src.get_center(), dst.get_center(), stroke_width=2, color=GRAY)
                    arrow = Arrow(line.get_start(), line.get_end(), buff=0.2, stroke_width=2, color=GRAY, max_tip_length_to_length_ratio=0.1)
                    edges.add(arrow)
                    arrows.append(arrow)
        network_group.add(edges)
        network_group.scale(0.6).to_edge(DOWN, buff=0.5)

        self.play(FadeIn(network_group))
        self.wait(0.5)

        # Animate gradient updates: small nudges on arrows
        for arrow in arrows:
            shift_vector = arrow.get_vector() * 0.05 * (np.random.random() - 0.5)
            self.play(arrow.animate.shift(shift_vector), run_time=0.1)

        self.wait(2)
