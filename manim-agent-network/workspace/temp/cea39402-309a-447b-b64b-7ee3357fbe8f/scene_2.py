from manim import *

class Scene2(Scene):
    def construct(self):
        # Title
        title = Text("Neural Network Layers", font_size=44).to_edge(UP)
        self.play(Write(title))
        self.wait(0.5)

        # Layer positions
        left_x, mid_x, right_x = -4, 0, 4
        input_y = [1.5, 0.5, -0.5]
        hidden_y = [2, 1, 0, -1]
        output_y = [0.5, -0.5]

        # Create neurons
        input_nodes = [Circle(radius=0.25, stroke_width=2, color=BLACK, fill_color=WHITE, fill_opacity=1)
                       .move_to([left_x, y, 0]) for y in input_y]
        hidden_nodes = [Circle(radius=0.25, stroke_width=2, color=BLACK, fill_color=WHITE, fill_opacity=1)
                        .move_to([mid_x, y, 0]) for y in hidden_y]
        output_nodes = [Circle(radius=0.25, stroke_width=2, color=BLACK, fill_color=WHITE, fill_opacity=1)
                        .move_to([right_x, y, 0]) for y in output_y]

        all_nodes = [*input_nodes, *hidden_nodes, *output_nodes]
        self.play(*[FadeIn(n) for n in all_nodes], run_time=1)
        self.wait(0.5)

        # Create connections with staggered animation
        connections = VGroup()
        for i, in_node in enumerate(input_nodes):
            for j, hid_node in enumerate(hidden_nodes):
                line = Line(in_node.get_center(), hid_node.get_center(), stroke_width=1.5, color=GREY)
                connections.add(line)
        for i, hid_node in enumerate(hidden_nodes):
            for j, out_node in enumerate(output_nodes):
                line = Line(hid_node.get_center(), out_node.get_center(), stroke_width=1.5, color=GREY)
                connections.add(line)

        # Staggered creation
        self.play(*[Create(c, run_time=1.2) for c in connections], lag_ratio=0.1)
        self.wait(0.5)

        # Soft glow on connections
        glow_lines = connections.copy().set_stroke(width=3, color=YELLOW).set_opacity(0.6)
        self.play(FadeIn(glow_lines), run_time=1)
        self.wait(0.5)

        # Group and center
        full = VGroup(*all_nodes, connections, glow_lines)
        full.scale_to_fit_width(12)
        full.move_to(ORIGIN)
        self.wait(2)
