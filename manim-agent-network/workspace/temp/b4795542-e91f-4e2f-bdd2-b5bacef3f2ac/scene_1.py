from manim import *

class Scene1(Scene):
    def construct(self):
        # Define vertices for a right-angled triangle at C
        A_point = [-4, 0, 0]
        B_point = [0, 3, 0]
        C_point = [0, 0, 0] # Right angle at C

        # Create the triangle lines
        side_b = Line(C_point, A_point) # Side opposite B (leg)
        side_a = Line(C_point, B_point) # Side opposite A (leg)
        side_c = Line(A_point, B_point) # Side opposite C (hypotenuse)

        triangle_lines = VGroup(side_a, side_b, side_c)

        # Create vertex labels using Text to avoid LaTeX dependency
        label_A = Text("A", font_size=48).next_to(A_point, DOWN + LEFT * 0.5)
        label_B = Text("B", font_size=48).next_to(B_point, UP + LEFT * 0.5)
        label_C = Text("C", font_size=48).next_to(C_point, DOWN + RIGHT * 0.5)
        vertex_labels = VGroup(label_A, label_B, label_C)

        # Create right angle mark at C
        # side_b (CA) points left, side_a (CB) points up. Angle is in top-left quadrant.
        right_angle_mark = RightAngle(side_b, side_a, length=0.4, quadrant=(-1,1))

        # Create side labels using Text to avoid LaTeX dependency
        label_side_a = Text("a", font_size=36).next_to(side_a, RIGHT * 0.5) # Label for side CB
        label_side_b = Text("b", font_size=36).next_to(side_b, DOWN * 0.5) # Label for side CA
        label_side_c = Text("c", font_size=36).next_to(side_c, UP * 0.5) # Label for side AB
        side_labels = VGroup(label_side_a, label_side_b, label_side_c)

        # Create text for Hypotenuse and Legs
        hypotenuse_text = Text("Hypotenuse", font_size=30).next_to(label_side_c, UP)
        # Position "Legs" text near the legs, outside the triangle
        legs_text = Text("Legs", font_size=30).move_to(C_point + LEFT * 1.5 + UP * 1.5)

        # --- Animations ---

        # 1. Create triangle and vertex labels
        self.play(Create(triangle_lines), Create(vertex_labels))
        self.wait(0.5)

        # 2. Mark the right angle
        self.play(Create(right_angle_mark))
        self.wait(0.5)

        # 3. FadeIn side labels 'a', 'b', 'c'
        self.play(FadeIn(side_labels))
        self.wait(0.5)

        # 4. FadeIn 'Hypotenuse' text
        self.play(FadeIn(hypotenuse_text))
        self.wait(0.5)

        # 5. FadeIn 'Legs' text
        self.play(FadeIn(legs_text))
        self.wait(1)

        # 6. Highlight side 'c' (hypotenuse)
        self.play(side_c.animate.set_color(YELLOW).set_stroke(width=6))
        self.wait(1)

        # 7. Highlight sides 'a' and 'b' (legs)
        self.play(
            side_a.animate.set_color(BLUE).set_stroke(width=6),
            side_b.animate.set_color(BLUE).set_stroke(width=6)
        )
        self.wait(2)
