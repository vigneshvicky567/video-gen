from manim import *

class Scene4(Scene):
    def construct(self):
        # Display the formula 'a^2 + b^2 = c^2'
        # Changed MathTex to MarkupText to avoid LaTeX dependency, addressing FileNotFoundError
        formula = MarkupText("a<sup>2</sup> + b<sup>2</sup> = c<sup>2</sup>")
        self.play(Write(formula))
        self.wait(1)

        # Move formula to top-left to make space for the example
        self.play(formula.animate.to_corner(UL).scale(0.7))
        self.wait(0.5)

        # Define points for the right-angled triangle (ladder example)
        ground_start = LEFT * 3
        ground_end = ORIGIN
        wall_end = UP * 3

        # Draw the ground
        ground = Line(ground_start, ground_end, color=BLUE)
        # Changed MathTex to Text for simple labels to avoid LaTeX dependency
        ground_label = Text("b").next_to(ground, DOWN)

        # Draw the wall
        wall = Line(ground_end, wall_end, color=GREEN)
        # Changed MathTex to Text for simple labels to avoid LaTeX dependency
        wall_label = Text("a").next_to(wall, LEFT)

        # Draw the ladder
        ladder = Line(ground_start, wall_end, color=RED)
        # Changed MathTex to Text for simple labels to avoid LaTeX dependency
        ladder_label = Text("c").next_to(ladder, UR) # Position label above and to the right

        # Group all example elements for easier manipulation
        example_elements = VGroup(ground, wall, ladder, ground_label, wall_label, ladder_label)

        # Animate drawing the example elements and their labels
        self.play(Create(ground), Create(wall), Create(ladder))
        self.wait(0.5)
        self.play(Write(ground_label), Write(wall_label), Write(ladder_label))
        self.wait(2)

        # Fade out the example elements
        self.play(FadeOut(example_elements))
        self.wait(0.5)

        # Move the formula back to the center and restore its original size
        self.play(formula.animate.center().scale(1/0.7))
        self.wait(0.5)

        # Pulsate/Glow effect for the formula
        self.play(
            formula.animate.scale(1.2),
            run_time=0.3
        )
        self.play(
            formula.animate.scale(1/1.2),
            run_time=0.3
        )
        # A second, slightly smaller pulse for emphasis
        self.play(
            formula.animate.scale(1.1),
            run_time=0.2
        )
        self.play(
            formula.animate.scale(1/1.1),
            run_time=0.2
        )
        self.wait(1)

        # Fade out the formula
        self.play(FadeOut(formula))
        self.wait(1)