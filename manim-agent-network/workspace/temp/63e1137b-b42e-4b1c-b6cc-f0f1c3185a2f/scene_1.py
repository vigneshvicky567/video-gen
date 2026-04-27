from manim import *

class Scene1(Scene):
    def construct(self):
        # 1. FadeIn: Title 'The Pythagorean Theorem'
        title = Text("The Pythagorean Theorem").scale(1.5)
        self.play(FadeIn(title))
        self.wait(1)

        # 2. FadeOut: Title (as per visual description's last step for the title)
        self.play(FadeOut(title))
        self.wait(0.5)

        # Define vertices for a right-angled triangle
        # C is the right angle vertex (origin)
        # B is on the x-axis, A is on the y-axis
        C_point = ORIGIN
        B_point = 3 * RIGHT
        A_point = 2 * UP

        # Create the triangle lines
        line_CB = Line(C_point, B_point) # Leg 'a'
        line_CA = Line(C_point, A_point) # Leg 'b'
        line_AB = Line(A_point, B_point) # Hypotenuse 'c'
        triangle_lines = VGroup(line_CB, line_CA, line_AB)

        # Label vertices A, B, C
        label_A = MathTex("A").next_to(A_point, UP + LEFT, buff=0.1)
        label_B = MathTex("B").next_to(B_point, DOWN + RIGHT, buff=0.1)
        label_C = MathTex("C").next_to(C_point, DOWN + LEFT, buff=0.1)
        vertex_labels = VGroup(label_A, label_B, label_C)

        # Add a small square symbol at the right angle vertex (C)
        # For C=ORIGIN, B=3R, A=2U, the angle is in the first quadrant relative to C.
        right_angle_symbol = RightAngle(line_CB, line_CA, length=0.4, quadrant=(1,1))

        # Label sides 'a', 'b', 'c'
        # Side 'a' is opposite A (line CB)
        label_side_a = MathTex("a").next_to(line_CB, DOWN, buff=0.1)
        # Side 'b' is opposite B (line CA)
        label_side_b = MathTex("b").next_to(line_CA, LEFT, buff=0.1)
        # Side 'c' is opposite C (line AB)
        label_side_c = MathTex("c").next_to(line_AB, UP + RIGHT, buff=0.1)
        side_labels = VGroup(label_side_a, label_side_b, label_side_c)

        # Draw: A right-angled triangle, with vertices labeled A, B, C.
        # Add: A small square symbol at the right angle vertex (e.g., at vertex C).
        # Label: Side opposite A as 'a', side opposite B as 'b', and side opposite C as 'c'.
        self.play(
            Create(triangle_lines),
            Create(right_angle_symbol),
            FadeIn(vertex_labels),
            FadeIn(side_labels)
        )
        self.wait(1)

        # Highlight: Sides 'a' and 'b' (legs) with a blue underline
        # Create "underline" lines slightly offset from the actual sides
        underline_a = line_CB.copy().shift(0.2 * DOWN).set_color(BLUE)
        underline_b = line_CA.copy().shift(0.2 * LEFT).set_color(BLUE)

        self.play(
            Create(underline_a),
            Create(underline_b),
            run_time=1.5
        )
        self.wait(1)

        # Highlight: then side 'c' (hypotenuse) with a red underline.
        # For a diagonal line, get_unit_normal() gives a vector perpendicular to the line.
        # For line_AB (from (0,2) to (3,0)), the unit normal pointing outwards is generally UP+RIGHT.
        underline_c = line_AB.copy().shift(line_AB.get_unit_normal() * 0.2).set_color(RED)

        self.play(
            Create(underline_c),
            run_time=1.5
        )
        self.wait(2)

        # Fade out all elements at the end of the scene
        self.play(
            FadeOut(triangle_lines),
            FadeOut(right_angle_symbol),
            FadeOut(vertex_labels),
            FadeOut(side_labels),
            FadeOut(underline_a),
            FadeOut(underline_b),
            FadeOut(underline_c)
        )
        self.wait(1)
