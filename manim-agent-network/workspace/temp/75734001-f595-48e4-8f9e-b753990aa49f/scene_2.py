from manim import *
import numpy as np

class Scene2(Scene):
    def construct(self):
        title = Text("Neural Network Layers", font_size=40).to_edge(UP)
        self.play(Write(title))
        self.wait(0.5)

        # Input layer: 2×2 grid of small blue squares
        input_squares = VGroup(*[
            Square(side_length=0.4, color=BLUE, fill_opacity=0.8)
            for _ in range(4)
        ])
        input_squares.arrange_in_grid(2, 2, buff=0.2)
        input_label = Text("Input", font_size=28).next_to(input_squares, DOWN)
        input_group = VGroup(input_squares, input_label).to_edge(LEFT, buff=1)
        self.play(FadeIn(input_group))
        self.wait(0.3)

        # Hidden Layer 1: 5 gray rounded rectangles
        h1_nodes = VGroup(*[
            RoundedRectangle(height=0.5, width=0.9, corner_radius=0.15, color=GRAY, fill_opacity=0.7)
            for _ in range(5)
        ])
        h1_nodes.arrange(DOWN, buff=0.3)
        h1_label = Text("Hidden Layer 1", font_size=28).next_to(h1_nodes, DOWN)
        h1_group = VGroup(h1_nodes, h1_label)
        h1_group.next_to(input_group, RIGHT, buff=2)

        # Animate sliding input into a horizontal stack
        self.play(input_squares.animate.arrange(RIGHT, buff=0.2).next_to(h1_group, LEFT, buff=1.5))
        self.wait(0.3)

        # Create arrows (edges) from input to h1
        arrows1 = VGroup()
        for sq in input_squares:
            for node in h1_nodes:
                arrow = Line(sq.get_right(), node.get_left(), stroke_width=1, color=WHITE)
                arrow.set_opacity(0)
                arrows1.add(arrow)
        self.play(*[arrow.animate.set_opacity(1).set_stroke(width=1.5) for arrow in arrows1], FadeIn(h1_group))
        self.wait(0.3)

        # Highlight h1 briefly
        self.play(h1_nodes.animate.set_fill(YELLOW, opacity=0.9), run_time=0.4)
        self.play(h1_nodes.animate.set_fill(GRAY, opacity=0.7), run_time=0.4)

        # Hidden Layer 2: 3 gray rounded rectangles
        h2_nodes = VGroup(*[
            RoundedRectangle(height=0.5, width=0.9, corner_radius=0.15, color=GRAY, fill_opacity=0.7)
            for _ in range(3)
        ])
        h2_nodes.arrange(DOWN, buff=0.3)
        h2_label = Text("Hidden Layer 2", font_size=28).next_to(h2_nodes, DOWN)
        h2_group = VGroup(h2_nodes, h2_label)
        h2_group.next_to(h1_group, RIGHT, buff=2)

        # Arrows from h1 to h2
        arrows2 = VGroup()
        for n1 in h1_nodes:
            for n2 in h2_nodes:
                arrow = Line(n1.get_right(), n2.get_left(), stroke_width=1, color=WHITE)
                arrow.set_opacity(0)
                arrows2.add(arrow)
        self.play(*[arrow.animate.set_opacity(1).set_stroke(width=1.5) for arrow in arrows2], FadeIn(h2_group))
        self.wait(0.3)

        # Highlight h2 briefly
        self.play(h2_nodes.animate.set_fill(YELLOW, opacity=0.9), run_time=0.4)
        self.play(h2_nodes.animate.set_fill(GRAY, opacity=0.7), run_time=0.4)

        # Output: single green circle
        output_node = Circle(radius=0.4, color=GREEN, fill_opacity=0.8)
        output_label = Text("Output", font_size=28).next_to(output_node, DOWN)
        output_group = VGroup(output_node, output_label)
        output_group.next_to(h2_group, RIGHT, buff=2)

        # Arrows from h2 to output
        arrows3 = VGroup()
        for n2 in h2_nodes:
            arrow = Line(n2.get_right(), output_node.get_left(), stroke_width=1, color=WHITE)
            arrow.set_opacity(0)
            arrows3.add(arrow)
        self.play(*[arrow.animate.set_opacity(1).set_stroke(width=1.5) for arrow in arrows3], FadeIn(output_group))
        self.wait(0.3)

        # Highlight output briefly
        self.play(output_node.animate.set_fill(YELLOW, opacity=1), run_time=0.4)
        self.play(output_node.animate.set_fill(GREEN, opacity=0.8), run_time=0.4)

        # Scale and center everything
        full = VGroup(input_group, h1_group, h2_group, output_group, arrows1, arrows2, arrows3)
        full.scale_to_fit_width(12)
        full.move_to(ORIGIN)
        self.wait(2)
