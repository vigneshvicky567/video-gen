from manim import *

class Scene4(Scene):
    def construct(self):
        # Define vertices for a right-angled triangle (e.g., 3-4-5 triangle)
        A = ORIGIN
        B = 4 * RIGHT
        C = 3 * UP

        # Create the triangle
        triangle = Polygon(A, B, C, color=WHITE, fill_opacity=0)
        
        # Create labels for the sides
        label_a = MathTex("a").next_to((A + C) / 2, LEFT) # Side AC (height)
        label_b = MathTex("b").next_to((A + B) / 2, DOWN) # Side AB (base)
        
        # For hypotenuse, position it along the side, shifted outwards
        hypotenuse_midpoint = (B + C) / 2
        # Calculate vector from C to B, rotate 90 deg counter-clockwise, and normalize for outward shift
        outward_normal_vector = rotate_vector(B - C, PI/2).normalize()
        label_c = MathTex("c").move_to(hypotenuse_midpoint).shift(0.3 * outward_normal_vector)

        # Group triangle and labels and position them
        triangle_group = VGroup(triangle, label_a, label_b, label_c).move_to(UP)

        # Formula for the Pythagorean Theorem
        formula = MathTex("a^2 + b^2 = c^2").scale(1.5).to_edge(DOWN).shift(UP)

        # Main title text
        pythagorean_theorem_text = Text("The Pythagorean Theorem").scale(0.8).next_to(formula, DOWN, buff=0.5)

        # --- Scene Animations ---

        # The original right-angled triangle from Scene 1 reappears.
        self.play(FadeIn(triangle_group))
        self.wait(0.5)

        # The formula 'a2 + b2 = c2' appears below the triangle using Write()
        self.play(Write(formula))
        self.wait(1)

        # As the narration mentions each term, 'a2', 'b2', and 'c2' on the formula briefly flash.
        # Indices for "a^2 + b^2 = c^2":
        # a^2: formula[0][0:3]
        # +:   formula[0][3]
        # b^2: formula[0][4:7]
        # =:   formula[0][7]
        # c^2: formula[0][8:11]

        # Flash a^2
        self.play(Flash(formula[0][0:3], flash_radius=0.3, color=YELLOW, duration=0.7))
        self.wait(0.5)

        # Flash b^2
        self.play(Flash(formula[0][4:7], flash_radius=0.3, color=YELLOW, duration=0.7))
        self.wait(0.5)

        # Flash c^2
        self.play(Flash(formula[0][8:11], flash_radius=0.3, color=YELLOW, duration=0.7))
        self.wait(1)

        # Text 'The Pythagorean Theorem' appears prominently at the bottom of the screen.
        self.play(Write(pythagorean_theorem_text))
        self.wait(2)

        # The entire scene gently fades to black.
        self.play(FadeOut(VGroup(triangle_group, formula, pythagorean_theorem_text)))
        self.wait(1) # Ensure everything is gone before scene ends