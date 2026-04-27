from manim import *
import numpy as np

class Scene3(Scene):
    def construct(self):
        # Define side lengths
        a = 2
        b = 3
        side_length = a + b
        c = np.sqrt(a**2 + b**2)

        # --- Left Square (a+b)^2 = a^2 + b^2 + 2ab ---
        large_square_left = Square(side_length=side_length).to_edge(LEFT, buff=1).shift(UP * 0.5)

        # Components of the left square
        sq_a = Square(side_length=a).set_color(BLUE).set_fill(BLUE, opacity=1).align_to(large_square_left, UL)
        sq_b = Square(side_length=b).set_color(GREEN).set_fill(GREEN, opacity=1).align_to(large_square_left, DR)
        rect_ab_tr = Rectangle(width=b, height=a).set_color(GREY).set_fill(GREY, opacity=1).next_to(sq_a, RIGHT, buff=0)
        rect_ab_bl = Rectangle(width=a, height=b).set_color(GREY).set_fill(GREY, opacity=1).next_to(sq_a, DOWN, buff=0)

        left_parts = VGroup(sq_a, sq_b, rect_ab_tr, rect_ab_bl)

        # Labels for left square
        # Changed MathTex to Text to avoid LaTeX dependency
        label_a_sq = Text("a^2").move_to(sq_a)
        label_b_sq = Text("b^2").move_to(sq_b)
        label_ab_tr = Text("ab").move_to(rect_ab_tr)
        label_ab_bl = Text("ab").move_to(rect_ab_bl)
        left_area_text = Text("Area = a^2 + b^2 + 2ab").next_to(large_square_left, DOWN)

        # --- Right Square (a+b)^2 = c^2 + 4 * (1/2 * ab) ---
        large_square_right = Square(side_length=side_length).to_edge(RIGHT, buff=1).shift(UP * 0.5)

        # Calculate vertices for the inner square and triangles
        center_right = large_square_right.get_center()
        half_s = side_length / 2

        # Corners of the large square (relative to its center)
        p1 = center_right + np.array([-half_s, -half_s, 0]) # DL
        p2 = center_right + np.array([half_s, -half_s, 0])  # DR
        p3 = center_right + np.array([half_s, half_s, 0])   # UR
        p4 = center_right + np.array([-half_s, half_s, 0])  # UL

        # Vertices of the inner square (rotated)
        # These points are (a,0), (s,a), (s-a,s), (0,s-a) relative to the bottom-left corner of the large square
        v1 = p1 + RIGHT * a
        v2 = p2 + UP * a
        v3 = p3 + LEFT * a
        v4 = p4 + DOWN * a

        c_sq_manim = Polygon(v1, v2, v3, v4).set_color(RED).set_fill(RED, opacity=1)

        # Four right-angled triangles
        tri_bl = Polygon(p1, v1, v4).set_color(YELLOW).set_fill(YELLOW, opacity=1)
        tri_br = Polygon(p2, v2, v1).set_color(YELLOW).set_fill(YELLOW, opacity=1)
        tri_tr = Polygon(p3, v3, v2).set_color(YELLOW).set_fill(YELLOW, opacity=1)
        tri_tl = Polygon(p4, v4, v3).set_color(YELLOW).set_fill(YELLOW, opacity=1)

        right_parts = VGroup(c_sq_manim, tri_bl, tri_br, tri_tr, tri_tl)

        # Labels for right square
        # Changed MathTex to Text to avoid LaTeX dependency
        label_c_sq = Text("c^2").move_to(c_sq_manim)
        # Simplified the expression for Text
        right_area_text = Text("Area = c^2 + 4 * (1/2 * ab)").next_to(large_square_right, DOWN)

        # --- Animations ---

        # 1. Draw large squares
        self.play(Create(large_square_left), Create(large_square_right))

        # 2. Draw internal components
        self.play(Create(left_parts), Create(right_parts))

        # 3. Label the regions
        self.play(
            FadeIn(label_a_sq),
            FadeIn(label_b_sq),
            FadeIn(label_ab_tr),
            FadeIn(label_ab_bl),
            FadeIn(label_c_sq)
        )

        # 4. Show area expressions
        self.play(FadeIn(left_area_text), FadeIn(right_area_text))
        self.wait(1)

        # 5. Fade out 'ab' labels and left area text
        self.play(
            FadeOut(label_ab_tr),
            FadeOut(label_ab_bl),
            FadeOut(left_area_text)
        )

        # 6. Shrink and fade out rectangles and triangles, and right area text
        # Replaced ShrinkAndFadeOut with FadeOut(..., scale=0.1) as ShrinkAndFadeOut is not a Manim animation
        self.play(
            FadeOut(rect_ab_tr, scale=0.1),
            FadeOut(rect_ab_bl, scale=0.1),
            FadeOut(tri_bl, scale=0.1),
            FadeOut(tri_br, scale=0.1),
            FadeOut(tri_tr, scale=0.1),
            FadeOut(tri_tl, scale=0.1),
            FadeOut(right_area_text)
        )

        # 7. Display final formula
        # Changed MathTex to Text to avoid LaTeX dependency
        final_formula = Text("a^2 + b^2 = c^2").scale(1.5).move_to(ORIGIN)
        self.play(FadeIn(final_formula))
        self.wait(2)
