from manim import *

class Scene1(Scene):
    def construct(self):
        # Define vertices for the right-angled triangle
        # Right angle at ORIGIN
        vertex_A = ORIGIN
        vertex_B = 4 * RIGHT
        vertex_C = 3 * UP

        # Create the triangle
        triangle = Polygon(vertex_A, vertex_B, vertex_C, color=WHITE)

        # Mark the right angle
        # FIX: The RightAngle constructor expects two Line objects or a VMobject and a vertex.
        # The previous call `RightAngle(triangle, vertex_A, ...)` seems to have incorrectly
        # passed vertex_A (a numpy.ndarray) as a 'line' object internally, causing the AttributeError.
        # Explicitly create the lines forming the angle at vertex_A.
        side_AB = Line(vertex_A, vertex_B)
        side_AC = Line(vertex_A, vertex_C)
        right_angle_marker = RightAngle(side_AB, side_AC, length=0.5, color=YELLOW)

        # Create labels for the sides
        label_a = MathTex("a").next_to(Line(vertex_A, vertex_C).get_center(), LEFT)
        label_b = MathTex("b").next_to(Line(vertex_A, vertex_B).get_center(), DOWN)
        # Using raw string for MathTex to correctly interpret \text
        label_c = MathTex("c", r"\text{ (hypotenuse)}").next_to(Line(vertex_B, vertex_C).get_center(), UP + RIGHT * 0.5)

        # Create the title text
        title_text = Text("Right-Angled Triangle", font_size=48).to_edge(UP)

        # Animate the scene
        self.play(Create(triangle))
        self.play(FadeIn(right_angle_marker))
        self.play(FadeIn(label_a), FadeIn(label_b), FadeIn(label_c))
        self.play(FadeIn(title_text))
        self.wait(2)
