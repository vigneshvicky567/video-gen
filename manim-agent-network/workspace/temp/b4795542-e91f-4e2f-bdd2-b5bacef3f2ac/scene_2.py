from manim import *

class Scene2(Scene):
    def construct(self):
        # Define vertices for a right-angled triangle (3-4-5 triangle)
        # A is the right angle vertex
        A = ORIGIN
        B = RIGHT * 4
        C = UP * 3

        # Create the triangle. Assumed to be present from a previous scene.
        triangle = Polygon(A, B, C, color=BLUE, fill_opacity=0.5, stroke_width=4)
        self.add(triangle)

        # --- Create squares on each side ---

        # Square on side 'a' (vertical leg AC, length 3)
        # Vertices: A, C, C + LEFT*3, A + LEFT*3
        sq_a = Polygon(A, C, C + LEFT * 3, A + LEFT * 3, color=RED, fill_opacity=0.2, stroke_width=2)
        # Changed MathTex to Text to avoid 'latex' FileNotFoundError
        a_label = Text("a^2", color=RED).move_to(sq_a.get_center())

        # Square on side 'b' (horizontal leg AB, length 4)
        # Vertices: A, B, B + DOWN*4, A + DOWN*4
        sq_b = Polygon(A, B, B + DOWN * 4, A + DOWN * 4, color=GREEN, fill_opacity=0.2, stroke_width=2)
        # Changed MathTex to Text to avoid 'latex' FileNotFoundError
        b_label = Text("b^2", color=GREEN).move_to(sq_b.get_center())

        # Square on side 'c' (hypotenuse BC, length 5)
        # Vector from B to C
        vec_BC = C - B
        # Rotate this vector by -PI/2 (clockwise) to get the direction for the square's third vertex
        # This builds the square "outwards" from the triangle
        rotated_vec_BC = rotate_vector(vec_BC, -PI/2)
        # Vertices: B, C, C + rotated_vec_BC, B + rotated_vec_BC
        sq_c = Polygon(B, C, C + rotated_vec_BC, B + rotated_vec_BC, color=YELLOW, fill_opacity=0.2, stroke_width=2)
        # Changed MathTex to Text to avoid 'latex' FileNotFoundError
        c_label = Text("c^2", color=YELLOW).move_to(sq_c.get_center())

        # --- Animations ---

        # Appear squares and labels
        self.play(GrowFromCenter(sq_a), Write(a_label))
        self.wait(0.5)
        self.play(GrowFromCenter(sq_b), Write(b_label))
        self.wait(0.5)
        self.play(GrowFromCenter(sq_c), Write(c_label))
        self.wait(1)

        # Formula 'a^2 + b^2 = c^2' appears
        # Changed MathTex to Text to avoid 'latex' FileNotFoundError
        formula = Text("a^2 + b^2 = c^2", color=WHITE).center().shift(DOWN * 2.5)
        self.play(Write(formula))
        self.wait(1)

        # Flash 'a^2' and 'b^2' squares
        self.play(
            Indicate(sq_a, color=RED, scale_factor=1.2),
            Indicate(sq_b, color=GREEN, scale_factor=1.2),
            run_time=1.5
        )
        self.wait(0.5)

        # Flash 'c^2' square
        self.play(
            Indicate(sq_c, color=YELLOW, scale_factor=1.2),
            run_time=1.5
        )
        self.wait(2)