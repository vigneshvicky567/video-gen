from manim import *

class Scene2(Scene):
    def construct(self):
        # Define base vertices for a right-angled triangle (e.g., a 3-4-5 triangle)
        base_A = ORIGIN
        base_B = RIGHT * 4
        base_C = UP * 3

        # Create the triangle shape
        triangle = Polygon(base_A, base_B, base_C, color=WHITE, fill_opacity=0.2)

        # Create lines for sides to help with labeling positions
        side_a_line = Line(base_A, base_C)
        side_b_line = Line(base_A, base_B)
        side_c_line = Line(base_B, base_C) # Hypotenuse

        # Labels for the sides of the triangle
        # Changed MathTex to Text to avoid LaTeX dependency issues
        label_a_side = Text("a").next_to(side_a_line, LEFT)
        label_b_side = Text("b").next_to(side_b_line, DOWN)
        label_c_side = Text("c").next_to(side_c_line, UP + RIGHT)

        # Group the triangle and its side labels
        triangle_and_labels = VGroup(triangle, label_a_side, label_b_side, label_c_side)

        # Position the entire triangle group to make space for squares
        shift_vector = LEFT * 1.5 + DOWN * 0.5
        triangle_and_labels.shift(shift_vector)

        # Now, define the *actual* shifted vertices for creating squares
        A = base_A + shift_vector
        B = base_B + shift_vector
        C = base_C + shift_vector

        # Display the initial triangle
        self.play(Create(triangle_and_labels))
        self.wait(1)

        # --- Square on side 'a' (vertical side) ---
        # Side 'a' is from A to C (length 3). Square extends to the left.
        square_a = Polygon(A, C, C + LEFT * 3, A + LEFT * 3,
                           color=BLUE, fill_opacity=0.5)
        # Changed MathTex to Text to avoid LaTeX dependency issues
        label_a_sq = Text("a^2", color=BLUE).move_to(square_a.get_center())
        self.play(Create(square_a), FadeIn(label_a_sq))
        self.wait(0.5)

        # --- Square on side 'b' (horizontal side) ---
        # Side 'b' is from A to B (length 4). Square extends downwards.
        square_b = Polygon(A, B, B + DOWN * 4, A + DOWN * 4,
                           color=GREEN, fill_opacity=0.5)
        # Changed MathTex to Text to avoid LaTeX dependency issues
        label_b_sq = Text("b^2", color=GREEN).move_to(square_b.get_center())
        self.play(Create(square_b), FadeIn(label_b_sq))
        self.wait(0.5)

        # --- Square on hypotenuse 'c' ---
        # Side 'c' is from B to C (length 5).
        # Calculate the vector along the hypotenuse.
        hypotenuse_vec = C - B
        # Calculate a perpendicular vector pointing outwards from the triangle.
        # This is achieved by rotating the hypotenuse vector clockwise by -PI/2 radians.
        perp_vec = rotate_vector(hypotenuse_vec, -PI/2)
        square_c = Polygon(B, C, C + perp_vec, B + perp_vec,
                           color=RED, fill_opacity=0.5)
        # Changed MathTex to Text to avoid LaTeX dependency issues
        label_c_sq = Text("c^2", color=RED).move_to(square_c.get_center())
        self.play(Create(square_c), FadeIn(label_c_sq))
        self.wait(0.5)

        # --- Final text label ---
        squares_on_sides_text = Text("Squares on Sides").next_to(triangle_and_labels, DOWN * 2)
        self.play(FadeIn(squares_on_sides_text))
        self.wait(2)