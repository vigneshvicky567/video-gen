from manim import *

class Scene2(Scene):
    def construct(self):
        # Define triangle vertices for a 3-4-5 right triangle
        A = ORIGIN
        B = 4 * RIGHT
        C = 3 * UP

        # Create the right triangle (assumed to be on screen from Scene 1)
        triangle = Polygon(A, B, C, color=WHITE, fill_opacity=0.5)
        self.add(triangle) # Add immediately as it's assumed to be present
        self.wait(0.5)

        # Define the lines for each side of the triangle
        # Side 'a' (base) is from A to B
        line_a = Line(A, B)
        # Side 'b' (height) is from A to C
        line_b = Line(A, C)
        # Side 'c' (hypotenuse) is from B to C
        line_c = Line(B, C)

        # --- Construct and animate the square on side 'a' ---
        # The triangle is above line_a, so the square is built downwards (direction=DOWN)
        square_a = Square.make_square_from_line(line_a, direction=DOWN)
        square_a.set_fill(BLUE_C, opacity=0.7)
        label_a = MathTex("a^2").move_to(square_a.get_center())
        label_a.set_color(BLACK) # Ensure text is readable on the colored square

        self.play(Create(square_a))
        self.play(FadeIn(label_a))
        self.wait(0.5)

        # --- Construct and animate the square on side 'b' ---
        # The triangle is to the right of line_b, so the square is built to the left (direction=LEFT)
        square_b = Square.make_square_from_line(line_b, direction=LEFT)
        square_b.set_fill(GREEN_C, opacity=0.7)
        label_b = MathTex("b^2").move_to(square_b.get_center())
        label_b.set_color(BLACK)

        self.play(Create(square_b))
        self.play(FadeIn(label_b))
        self.wait(0.5)

        # --- Construct and animate the square on side 'c' ---
        # For the hypotenuse, line_c.get_unit_normal() provides the correct outward direction
        # (C-B) vector is (-4, 3). Its normal (C-B).rotate(PI/2) is (-3, -4), which points outwards.
        square_c = Square.make_square_from_line(line_c, direction=line_c.get_unit_normal())
        square_c.set_fill(RED_C, opacity=0.7)
        label_c = MathTex("c^2").move_to(square_c.get_center())
        label_c.set_color(BLACK)

        self.play(Create(square_c))
        self.play(FadeIn(label_c))
        self.wait(2) # Keep all elements on screen for a final view