from manim import *
import numpy as np

class Scene3(Scene):
    def construct(self):
        title = Text("Forward Pass & Activation", font_size=44).to_edge(UP)
        self.play(Write(title))
        self.wait(0.5)

        # Layer positions
        top_y = 1.5
        mid_y = 0
        bot_y = -1.5
        left_x = -2
        right_x = 2

        # Input nodes
        in_vals = [0.7, 0.2, 0.9]
        in_nodes = VGroup(*[Circle(radius=0.25, color=WHITE).move_to(np.array([left_x, top_y - i*0.8, 0])) for i in range(3)])
        in_labels = VGroup(*[Text(str(v), font_size=28).move_to(n.get_center()) for v, n in zip(in_vals, in_nodes)])
        self.play(FadeIn(in_nodes), FadeIn(in_labels))
        self.wait(0.3)

        # Output nodes
        out_vals = [0.8, 0.1]
        out_nodes = VGroup(*[Circle(radius=0.25, color=WHITE).move_to(np.array([right_x, mid_y + (0.5 - i)*0.8, 0])) for i in range(2)])
        out_labels = VGroup(*[Text(str(v), font_size=28).move_to(n.get_center()) for v, n in zip(out_vals, out_nodes)])
        self.play(FadeIn(out_nodes))
        self.wait(0.3)

        # Edges with weights
        weights = [[0.5, 0.4], [0.3, 0.7], [0.6, 0.2]]
        edges = VGroup()
        weight_labels = VGroup()
        for i, inode in enumerate(in_nodes):
            for j, onode in enumerate(out_nodes):
                line = Line(inode.get_right(), onode.get_left(), stroke_width=3, color=interpolate_color(BLUE, RED, weights[i][j]))
                label = Text(f"{weights[i][j]:.1f}", font_size=22, color=line.get_color()).move_to(line.get_center()).scale(0.7)
                edges.add(line)
                weight_labels.add(label)
        self.play(Create(edges), FadeIn(weight_labels))
        self.wait(0.5)

        # Animate data flow
        dots = VGroup()
        for i, inode in enumerate(in_nodes):
            for j, onode in enumerate(out_nodes):
                dot = Dot(inode.get_right(), radius=0.08, color=YELLOW)
                dots.add(dot)
                self.add(dot)
                self.play(dot.animate.move_to(onode.get_left()), run_time=0.6)
                self.remove(dot)
        self.wait(0.3)

        # Compute weighted sums
        sums = [0.0, 0.0]
        for j in range(2):
            s = 0
            for i in range(3):
                s += in_vals[i] * weights[i][j]
            sums[j] = s

        sum_labels = VGroup(*[Text(f"{s:.2f}", font_size=28).next_to(onode, DOWN) for s, onode in zip(sums, out_nodes)])
        self.play(Transform(out_labels, sum_labels))
        self.wait(0.5)

        # Sigmoid curve overlay
        sig_axes = Axes(x_range=[-1, 5], y_range=[0, 1.2], x_length=6, y_length=3).to_edge(DOWN)
        sig_curve = sig_axes.plot(lambda x: 1/(1+np.exp(-x)), color=GREEN)
        sig_label = Text("Sigmoid", font_size=28).next_to(sig_axes, UP)
        self.play(Create(sig_axes), Create(sig_curve), Write(sig_label))
        self.wait(0.5)

        # Animate sigmoid application
        sig_out = [1/(1+np.exp(-s)) for s in sums]
        sig_out_labels = VGroup(*[Text(f"{sig:.2f}", font_size=28).move_to(onode.get_center()) for sig in sig_out])
        self.play(Transform(out_labels, sig_out_labels))
        self.wait(0.5)

        # Final layout
        all_objs = VGroup(title, in_nodes, in_labels, out_nodes, out_labels, edges, weight_labels, sig_axes, sig_curve, sig_label)
        all_objs.scale_to_fit_width(12)
        all_objs.move_to(ORIGIN)
        self.wait(2)
